"""Gradio UI for the Diary Transcript app — record, transcribe, history.

**Secondary surface:** the product path is CLI + local daemon + Tauri.
This UI is kept for quick browser demos; STT goes through SessionService
(same path as CLI/API), not direct backend imports.
"""
from __future__ import annotations

from pathlib import Path

import gradio as gr

from ..config import load_config

load_config()
from ..core.history import (
    DEFAULT_DIARY_DIR,
    list_entries,
    get_entry,
    load_transcript_data,
    load_analysis_data,
    format_transcript_text,
    format_entry_summary,
)
from ..core.speakers import (
    get_entry_speaker_map,
    set_entry_speaker_map,
    parse_rename_pairs,
    display_speakers_for_entry,
    raw_labels_from_transcript_data,
    filter_entries_by_person,
    roster_for_api,
)
from ..core.search import search_diary, get_entry_segments
from ..core.export import export_entry
from ..core.digest import digests_for_api, write_digest
from ..core.annotate import update_entry_annotation
from ..core.actions import ActionInbox, inbox_for_api
from ..services.session import (
    format_key_points_markdown,
    format_transcript_lines,
    get_session_service,
)

DIARY_DIR = DEFAULT_DIARY_DIR
DIARY_DIR.mkdir(parents=True, exist_ok=True)

# Alias for any residual call sites / notebooks
format_analysis = format_key_points_markdown


def record_button_action(duration: float, sr: int):
    """Record via SessionService / pipeline (sample rate is fixed at 16 kHz)."""
    del sr  # AudioConfig in pipeline is 16 kHz mono
    try:
        svc = get_session_service()
        wav = svc.record(duration=float(duration), diary_dir=DIARY_DIR)
        return str(wav), "Recording saved successfully."
    except Exception as e:
        return None, f"Recording error: {e}"


def transcribe_button_action(wav_file, backend_type, backend_size, max_speakers, device="auto"):
    """Transcribe via SessionService (registry backends + warm cache)."""
    wav_path = Path(wav_file) if wav_file else None
    if not wav_path or not Path(wav_path).exists():
        return "", "No audio file selected.", "", ""

    svc = get_session_service()
    model_size = backend_size if (backend_type or "").lower() == "whisper" else None
    result = svc.run(
        audio_path=wav_path,
        backend=backend_type or "moss",
        device=device or "auto",
        diary_dir=DIARY_DIR,
        max_speakers=int(max_speakers) if max_speakers is not None else None,
        model_size=model_size,
        use_cache=True,
    )
    if not result.ok:
        return "", f"Transcription error: {result.error}", "", ""

    segs = (result.transcript or {}).get("segments") or []
    if not segs:
        return "No speech detected in the audio.", "", "", ""

    transcript_text = format_transcript_lines(result.transcript)
    analysis_text = format_key_points_markdown(result.key_points)
    return (
        transcript_text,
        analysis_text,
        result.transcript_path or "",
        result.analysis_path or "",
    )


def load_latest_action(backend_type, backend_size, max_speakers, device="auto"):
    recordings = sorted(
        list(DIARY_DIR.glob("recording_*.wav"))
        + (
            list((DIARY_DIR / "tmp").glob("recording_*.wav"))
            if (DIARY_DIR / "tmp").exists()
            else []
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not recordings:
        return "", "No recordings found.", "", ""
    return transcribe_button_action(
        str(recordings[0]), backend_type, backend_size, max_speakers, device
    )


# ─── History ───────────────────────────────────────────────────────────────────

def _history_choices(limit: int = 100, person: str | None = None) -> list[str]:
    if person and person.strip():
        entries = filter_entries_by_person(person.strip(), diary_dir=DIARY_DIR, limit=limit)
    else:
        entries = list_entries(DIARY_DIR, limit=limit)
    choices = []
    for e in entries:
        flags = []
        if e.has_audio:
            flags.append("audio")
        if e.has_transcript:
            flags.append("tx")
        flag = ",".join(flags) if flags else "empty"
        who = ", ".join(display_speakers_for_entry(e, diary_dir=DIARY_DIR)) or "?"
        label = f"{e.id}  [{flag}]  [{who}]  {e.preview[:60]}"
        choices.append(label)
    return choices


def refresh_history(person_filter: str = ""):
    choices = _history_choices(person=person_filter or None)
    if not choices:
        msg = "No history yet." if not person_filter else f"No entries for “{person_filter}”."
        return gr.update(choices=[], value=None), msg
    return (
        gr.update(choices=choices, value=choices[0]),
        f"{len(choices)} entries (newest first)"
        + (f" · filter: {person_filter}" if person_filter else ""),
    )


def _segment_choices(entry_id: str) -> list[str]:
    segs = get_entry_segments(entry_id, diary_dir=DIARY_DIR)
    choices = []
    for s in segs:
        label = (
            f"[{s['start']:.1f}s] {s['speaker']}: "
            f"{(s['text'] or '')[:70]}"
        )
        # encode start time at end for seek parser
        choices.append(f"{label}  ·@{s['start']:.3f}")
    return choices


def open_history_entry(selection: str):
    empty_segs = gr.update(choices=[], value=None)
    if not selection:
        return None, "", "", "Select an entry from the list.", "", "", empty_segs, ""
    entry_id = selection.split()[0].strip()
    entry = get_entry(entry_id, DIARY_DIR)
    if not entry:
        return None, "", "", f"Entry not found: {entry_id}", "", "", empty_segs, ""

    audio = entry.audio_path if entry.has_audio else None
    tx_data = load_transcript_data(entry)
    smap = get_entry_speaker_map(entry, DIARY_DIR)
    tx_text = format_transcript_text(tx_data, speaker_map=smap) if tx_data else "(no transcript)"
    analysis = load_analysis_data(entry)
    if analysis:
        kp = analysis.get("key_points", analysis)
        analysis_text = format_analysis(kp if isinstance(kp, dict) else {})
    else:
        analysis_text = ""

    who = ", ".join(display_speakers_for_entry(entry, diary_dir=DIARY_DIR)) or "—"
    raw = raw_labels_from_transcript_data(tx_data) if tx_data else []
    map_str = ", ".join(f"{k}→{v}" for k, v in smap.items()) if smap else "(none)"
    rename_hint = " ".join(f'"{r}=Name"' for r in raw) if raw else '"Speaker 1=Alex"'

    meta = (
        f"**{entry.id}** — {format_entry_summary(entry)}\n\n"
        f"- Speakers: **{who}**\n"
        f"- Map: `{map_str}`\n"
        f"- Raw labels: `{', '.join(raw) or '—'}`\n"
        f"- Title: {entry.title}\n"
        f"- Audio: `{entry.audio_path or '—'}`\n"
        f"- Backend: {entry.backend or '—'}\n\n"
        f"_Select a segment below to seek audio to that timestamp._"
    )
    if smap:
        rename_default = " ".join(f"{k}={v}" for k, v in smap.items())
    else:
        rename_default = " ".join(f"{r}=" for r in raw)

    seg_choices = _segment_choices(entry_id)
    seg_update = gr.update(choices=seg_choices, value=None)
    return audio, tx_text, analysis_text, meta, rename_default, rename_hint, seg_update, ""


def seek_segment(selection: str, segment_label: str, audio_path: str | None):
    """Return HTML audio that starts at the segment timestamp."""
    if not segment_label:
        return "", "Pick a segment to seek."
    import re
    m = re.search(r"·@([0-9.]+)$", segment_label.strip())
    if not m:
        return "", "Could not parse segment time."
    start = float(m.group(1))
    # Prefer audio from open entry path passed in
    path = audio_path
    if not path and selection:
        entry = get_entry(selection.split()[0].strip(), DIARY_DIR)
        if entry and entry.has_audio:
            path = entry.audio_path
    if not path:
        return "", f"No audio file (would seek to {start:.1f}s)."
    # file= URL works in Gradio for local paths
    safe = str(path).replace("'", "%27")
    html = f"""
    <div>
      <p><b>Seek → {start:.1f}s</b></p>
      <audio controls autoplay style="width:100%"
        src="/file={safe}"
        onloadedmetadata="this.currentTime={start}; this.play();">
      </audio>
    </div>
    """
    return html, f"Seeking to {start:.1f}s"


def run_search(query: str, person: str):
    hits = search_diary(query or "", person=person or None, limit=40, diary_dir=DIARY_DIR)
    if not hits:
        return gr.update(choices=[], value=None), "No matches.", "", None, gr.update(choices=[], value=None)
    choices = []
    for h in hits:
        n = len(h.segments)
        choices.append(
            f"{h.entry_id}  score={h.score:.1f}  segs={n}  "
            f"[{', '.join(h.speakers) or '—'}]  {(h.title or h.preview)[:50]}"
        )
    # build detail for first hit
    detail, audio, segs = _search_hit_detail(hits[0])
    return (
        gr.update(choices=choices, value=choices[0]),
        f"{len(hits)} matching entries",
        detail,
        audio,
        gr.update(choices=segs, value=None),
    )


def _search_hit_detail(hit) -> tuple[str, str | None, list[str]]:
    lines = [
        f"### {hit.entry_id}",
        f"**{hit.created_at}** · score {hit.score:.2f} · matched: {', '.join(hit.match_fields)}",
        f"Speakers: {', '.join(hit.speakers) or '—'}",
        f"Audio: `{hit.audio_path or '—'}`",
        "",
        "#### Matching segments (select to seek)",
    ]
    seg_choices = []
    for s in hit.segments:
        lines.append(f"- **[{s.start:.1f}s]** {s.speaker}: {s.snippet}")
        seg_choices.append(
            f"[{s.start:.1f}s] {s.speaker}: {(s.text or '')[:70]}  ·@{s.start:.3f}"
        )
    if not hit.segments:
        # fall back to all segments for seek
        seg_choices = _segment_choices(hit.entry_id)
        lines.append("_No segment text hits — listing all segments for seek._")
    return "\n".join(lines), hit.audio_path, seg_choices


def open_search_hit(selection: str, query: str, person: str):
    if not selection:
        return "Select a search result.", None, gr.update(choices=[], value=None)
    entry_id = selection.split()[0].strip()
    hits = search_diary(query or "", person=person or None, limit=100, diary_dir=DIARY_DIR)
    hit = next((h for h in hits if h.entry_id == entry_id), None)
    if not hit:
        # still open entry segments
        segs = _segment_choices(entry_id)
        entry = get_entry(entry_id, DIARY_DIR)
        audio = entry.audio_path if entry and entry.has_audio else None
        return f"**{entry_id}**", audio, gr.update(choices=segs, value=None)
    detail, audio, segs = _search_hit_detail(hit)
    return detail, audio, gr.update(choices=segs, value=None)


def apply_rename(selection: str, rename_text: str, remember: bool):
    empty = (
        None, "", "", "Select an entry first.", "", "",
        gr.update(choices=[], value=None), "", "Select an entry first.",
    )
    if not selection:
        return empty
    entry_id = selection.split()[0].strip()
    import re
    text = rename_text or ""
    parts = re.findall(
        r"(?:Speaker\s*\d+|S\d+)\s*[=:]\s*\S+",
        text,
        flags=re.IGNORECASE,
    )
    if not parts:
        for tok in text.replace("\n", " ").split():
            if "=" in tok or ":" in tok:
                parts.append(tok.strip("'\""))
    try:
        mapping = parse_rename_pairs(parts)
        if not mapping:
            base = open_history_entry(selection)
            return (*base, "No valid LABEL=Name pairs found.")
        set_entry_speaker_map(
            entry_id, mapping, diary_dir=DIARY_DIR, remember=bool(remember)
        )
        base = open_history_entry(selection)
        note = f"Saved renames for {entry_id}" + (" (remembered defaults)" if remember else "")
        return (*base, note)
    except Exception as e:
        base = open_history_entry(selection)
        return (*base, f"Rename failed: {e}")


def roster_markdown():
    data = roster_for_api(DIARY_DIR)
    people = data.get("people") or []
    if not people:
        return "_No known people yet. Rename speakers on an entry to build the roster._"
    lines = ["**Known people**"]
    for p in people:
        lines.append(f"- **{p['name']}** (used {p.get('use_count', 0)}×)")
    defaults = data.get("global_defaults") or {}
    if defaults:
        lines.append("\n**Remembered defaults**")
        for k, v in defaults.items():
            lines.append(f"- {k} → {v}")
    return "\n".join(lines)


def create_ui():
    with gr.Blocks(title="Diary Transcript", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 🎙️ Diary Transcript")
        gr.Markdown(
            "Record, transcribe, and browse history. "
            "Default model: **MOSS-Transcribe-Diarize** (Mac + PC)."
        )

        with gr.Accordion("Settings", open=False):
            with gr.Row():
                backend_type = gr.Radio(
                    ["moss", "whisper", "nemo"],
                    value="moss",
                    label="Backend",
                    interactive=True,
                )
                backend_size = gr.Radio(
                    ["small", "medium"],
                    value="medium",
                    label="Model Size (Whisper only)",
                    interactive=True,
                )
                max_speakers = gr.Slider(
                    1, 8, value=4, step=1, label="Max Speakers", interactive=True
                )
                device_choice = gr.Radio(
                    ["auto", "cuda", "mps", "cpu"],
                    value="auto",
                    label="Device (auto = CUDA → MPS → CPU)",
                    interactive=True,
                )
                sample_rate = gr.Radio(
                    [16000], value=16000, label="Sample Rate (Hz)", interactive=False
                )

        with gr.Tab("Actions"):
            gr.Markdown(
                "Cross-session **action inbox**. Syncs from analyses; mark items done."
            )
            btn_sync_actions = gr.Button("Sync from history", variant="secondary")
            actions_md = gr.Markdown("")
            with gr.Row():
                action_id_box = gr.Textbox(label="Action id", scale=2)
                btn_done_action = gr.Button("Mark done", variant="primary", scale=1)
            action_status = gr.Markdown("")

            def refresh_actions():
                data = inbox_for_api(sync=True)
                lines = [
                    f"**Open: {data['open_count']}** · Done: {data['done_count']} "
                    f"(+{data['synced_new']} new from sync)"
                ]
                for it in data["open"][:40]:
                    lines.append(f"- ☐ `{it['id']}` {it['text']}  \n  _{it.get('entry_id') or ''}_")
                if data["done"]:
                    lines.append("\n**Recently done**")
                    for it in data["done"][:10]:
                        lines.append(f"- ✓ ~~{it['text']}~~")
                return "\n".join(lines)

            def mark_action_done(aid):
                if not aid:
                    return refresh_actions(), "Enter an action id"
                try:
                    ActionInbox().mark_done(aid.strip(), True)
                    return refresh_actions(), f"Done: {aid}"
                except Exception as e:
                    return refresh_actions(), str(e)

            btn_sync_actions.click(fn=refresh_actions, outputs=[actions_md])
            btn_done_action.click(
                fn=mark_action_done,
                inputs=[action_id_box],
                outputs=[actions_md, action_status],
            )

        with gr.Tab("Digest"):
            gr.Markdown(
                "Roll up the last **N active days** into decisions, action items, and session summaries."
            )
            with gr.Row():
                digest_days = gr.Slider(1, 30, value=7, step=1, label="Active days")
                btn_digest = gr.Button("Build digest", variant="primary")
            digest_md = gr.Markdown("")
            digest_path = gr.Textbox(label="Saved to", interactive=False)

            def build_digest_ui(days):
                data = digests_for_api(days=int(days))
                path = write_digest(days=int(days), fmt="md")
                return data.get("markdown") or "_empty_", str(path)

            btn_digest.click(
                fn=build_digest_ui,
                inputs=[digest_days],
                outputs=[digest_md, digest_path],
            )

        with gr.Tab("Search"):
            gr.Markdown(
                "Full-text search across transcripts and analysis. "
                "Open a hit, then **select a segment to seek the audio** to that time."
            )
            with gr.Row():
                search_query = gr.Textbox(
                    label="Query",
                    placeholder='e.g. budget  or  "next week"',
                    scale=3,
                )
                search_person = gr.Textbox(
                    label="Person (optional)",
                    placeholder="Alex",
                    scale=1,
                )
                btn_search = gr.Button("Search", variant="primary", scale=1)
            search_status = gr.Markdown("")
            search_results = gr.Dropdown(label="Matches", interactive=True)
            search_detail = gr.Markdown("")
            search_audio_path = gr.State(None)
            search_audio = gr.Audio(label="Audio", type="filepath", interactive=False)
            search_segments = gr.Dropdown(
                label="Segments — select to seek",
                interactive=True,
            )
            search_seek_html = gr.HTML("")
            search_seek_status = gr.Markdown("")

            btn_search.click(
                fn=run_search,
                inputs=[search_query, search_person],
                outputs=[
                    search_results,
                    search_status,
                    search_detail,
                    search_audio,
                    search_segments,
                ],
            ).then(
                fn=lambda a: a,
                inputs=[search_audio],
                outputs=[search_audio_path],
            )
            search_query.submit(
                fn=run_search,
                inputs=[search_query, search_person],
                outputs=[
                    search_results,
                    search_status,
                    search_detail,
                    search_audio,
                    search_segments,
                ],
            )
            search_results.change(
                fn=open_search_hit,
                inputs=[search_results, search_query, search_person],
                outputs=[search_detail, search_audio, search_segments],
            ).then(
                fn=lambda a: a,
                inputs=[search_audio],
                outputs=[search_audio_path],
            )
            search_segments.change(
                fn=seek_segment,
                inputs=[search_results, search_segments, search_audio_path],
                outputs=[search_seek_html, search_seek_status],
            )

        with gr.Tab("History"):
            gr.Markdown(
                "Browse past sessions newest-first. Select an entry to **read the transcript**, "
                "**listen to audio**, **seek by segment**, and **rename speakers**."
            )
            with gr.Row():
                person_filter = gr.Textbox(
                    label="Filter by person",
                    placeholder="e.g. Alex",
                    scale=2,
                )
                btn_refresh = gr.Button("Refresh history", variant="secondary", scale=1)
            history_status = gr.Markdown("")
            roster_md = gr.Markdown(roster_markdown())
            history_dropdown = gr.Dropdown(
                label="Past entries (newest first)",
                choices=_history_choices(),
                interactive=True,
            )
            history_meta = gr.Markdown("")
            history_audio = gr.Audio(label="Audio playback", type="filepath", interactive=False)
            history_audio_path = gr.State(None)
            history_segments = gr.Dropdown(
                label="Segments — select to seek audio",
                interactive=True,
            )
            history_seek_html = gr.HTML("")
            history_seek_status = gr.Markdown("")
            history_transcript = gr.Textbox(label="Transcript", lines=16, interactive=False)
            history_analysis = gr.Textbox(label="Analysis", lines=8, interactive=False)
            with gr.Row():
                rename_box = gr.Textbox(
                    label="Rename speakers (LABEL=Name …)",
                    placeholder='Speaker 1=Alex Speaker 2=Me',
                    scale=3,
                )
                remember_chk = gr.Checkbox(label="Remember as defaults", value=True, scale=1)
                btn_rename = gr.Button("Save names", variant="primary", scale=1)
            rename_status = gr.Markdown("")
            rename_hint = gr.Markdown("")
            with gr.Row():
                btn_export = gr.Button("Export entry (MD/SRT/TXT/JSON)", variant="secondary")
                btn_star = gr.Button("★ Star / unstar", variant="secondary")
            with gr.Row():
                tag_input = gr.Textbox(label="Add tags (space-separated)", placeholder="meeting 1:1 project-x")
                btn_add_tags = gr.Button("Add tags")
            note_input = gr.Textbox(label="Append note", lines=2)
            btn_note = gr.Button("Save note")
            export_status = gr.Markdown("")

            def export_selected(selection):
                if not selection:
                    return "Select an entry first."
                eid = selection.split()[0].strip()
                try:
                    r = export_entry(eid)
                    files = "\n".join(f"- `{f}`" for f in r.files)
                    return f"**Exported {r.entry_id}** to `{r.out_dir}`\n\n{files}"
                except Exception as e:
                    return f"Export failed: {e}"

            def star_selected(selection):
                if not selection:
                    return "Select an entry first."
                eid = selection.split()[0].strip()
                e = get_entry(eid, DIARY_DIR)
                if not e:
                    return "Not found"
                update_entry_annotation(eid, starred=not e.starred)
                e2 = get_entry(eid, DIARY_DIR)
                return f"{'★ Starred' if e2 and e2.starred else '☆ Unstarred'} {eid}"

            def tags_selected(selection, tags):
                if not selection:
                    return "Select an entry first."
                eid = selection.split()[0].strip()
                add = [t for t in (tags or "").replace(",", " ").split() if t]
                e = update_entry_annotation(eid, add_tags=add)
                return f"Tags on {e.id}: {', '.join('#'+t for t in e.tags) or '—'}"

            def note_selected(selection, note):
                if not selection or not note:
                    return "Select entry and enter a note."
                eid = selection.split()[0].strip()
                e = update_entry_annotation(eid, append_note=note)
                return f"Notes on {e.id}:\n{e.notes}"

            btn_export.click(
                fn=export_selected,
                inputs=[history_dropdown],
                outputs=[export_status],
            )
            btn_star.click(fn=star_selected, inputs=[history_dropdown], outputs=[export_status])
            btn_add_tags.click(
                fn=tags_selected,
                inputs=[history_dropdown, tag_input],
                outputs=[export_status],
            )
            btn_note.click(
                fn=note_selected,
                inputs=[history_dropdown, note_input],
                outputs=[export_status],
            )

            btn_refresh.click(
                fn=refresh_history,
                inputs=[person_filter],
                outputs=[history_dropdown, history_status],
            )
            person_filter.submit(
                fn=refresh_history,
                inputs=[person_filter],
                outputs=[history_dropdown, history_status],
            )
            history_dropdown.change(
                fn=open_history_entry,
                inputs=[history_dropdown],
                outputs=[
                    history_audio,
                    history_transcript,
                    history_analysis,
                    history_meta,
                    rename_box,
                    rename_hint,
                    history_segments,
                    history_seek_status,
                ],
            ).then(
                fn=lambda a: a,
                inputs=[history_audio],
                outputs=[history_audio_path],
            )
            history_segments.change(
                fn=seek_segment,
                inputs=[history_dropdown, history_segments, history_audio_path],
                outputs=[history_seek_html, history_seek_status],
            )
            btn_rename.click(
                fn=apply_rename,
                inputs=[history_dropdown, rename_box, remember_chk],
                outputs=[
                    history_audio,
                    history_transcript,
                    history_analysis,
                    history_meta,
                    rename_box,
                    rename_hint,
                    history_segments,
                    history_seek_status,
                    rename_status,
                ],
            ).then(
                fn=lambda: roster_markdown(),
                inputs=[],
                outputs=[roster_md],
            )

        with gr.Tab("File"):
            file_input = gr.File(label="Upload Audio File", type="filepath")
            with gr.Row():
                btn_transcribe = gr.Button("Transcribe File", variant="primary")
                btn_load_latest = gr.Button("Load Latest Recording", variant="secondary")
            transcript_output = gr.Textbox(label="Transcript", lines=15, interactive=False)
            analysis_output = gr.Textbox(label="Analysis", lines=10, interactive=False)
            with gr.Row():
                transcript_path = gr.Textbox(label="Transcript Saved", lines=1, interactive=False)
                analysis_path = gr.Textbox(label="Analysis Saved", lines=1, interactive=False)

        with gr.Tab("Record"):
            duration_input = gr.Slider(
                10, 300, value=60, step=5, label="Recording Duration (seconds)", interactive=True
            )
            with gr.Row():
                btn_record = gr.Button("Start Recording", variant="primary")
            recording_output = gr.Textbox(label="Recording Status", lines=1, interactive=False)
            wav_file_output = gr.File(label="Recording", interactive=False)

        btn_transcribe.click(
            fn=transcribe_button_action,
            inputs=[file_input, backend_type, backend_size, max_speakers, device_choice],
            outputs=[transcript_output, analysis_output, transcript_path, analysis_path],
        )
        btn_load_latest.click(
            fn=load_latest_action,
            inputs=[backend_type, backend_size, max_speakers, device_choice],
            outputs=[transcript_output, analysis_output, transcript_path, analysis_path],
        )
        btn_record.click(
            fn=record_button_action,
            inputs=[duration_input, sample_rate],
            outputs=[wav_file_output, recording_output],
        )

    return app


if __name__ == "__main__":
    import os

    ui = create_ui()
    host = os.environ.get("DIARY_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("DIARY_UI_PORT", "7860"))
    ui.launch(server_name=host, server_port=port, share=False)
