"""CLI command handlers (moved out of main.py).

main.py owns argparse + process entry; this module owns command implementations.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from diary_app.core.audio import AudioConfig
from diary_app.core.transcribe import Transcript, KeyPoints
from diary_app.core.analyzer import TranscriptAnalyzer
from diary_app.core.logutil import get_logger
from diary_app.config import get_config, write_example_config
from diary_app.cli import handlers as cli_handlers

console = Console()
log = get_logger("cli")

# Updated each process start from AppConfig in main()
DIARY_DIR = Path.home() / "diary"
BACKEND_CHOICES = ("auto", "moss", "whisper", "nemo")


def resolve_output_path(output: str | Path | None, default_name: str) -> Path:
    """Treat --output as a file if it has a suffix, else as a directory."""
    if output is None:
        path = DIARY_DIR / default_name
    else:
        path = Path(output).expanduser()
        if path.suffix.lower() in {".json", ".txt", ".wav"}:
            pass
        else:
            path = path / default_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def do_record(args: argparse.Namespace) -> Path:
    """Record audio from the microphone."""
    console.print(Panel("🎙 Recording", style="bold cyan"))

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devices = [
            (i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0
        ]
    except Exception:
        input_devices = []

    if not input_devices:
        console.print(Panel(
            "[red]No microphone input devices found![/red]\n\n"
            "If you're in WSL, audio capture isn't supported. Use "
            "[cyan]python -m diary_app transcribe <file>[/cyan] with a pre-recorded file.\n\n"
            "Or run on Mac/Linux/Windows with direct audio access.",
            style="bold red",
        ))
        sys.exit(1)

    if sys.stdin.isatty() and len(input_devices) > 1:
        for local_i, (dev_i, d) in enumerate(input_devices):
            console.print(f"  [{local_i}] {d['name']} (id={dev_i})")
        try:
            choice = int(input(f"Choose device [0-{len(input_devices) - 1}]: "))
        except (ValueError, EOFError):
            choice = 0
        choice = max(0, min(choice, len(input_devices) - 1))
        device_id = input_devices[choice][0]
    else:
        device_id = input_devices[0][0]

    if args.duration:
        config = AudioConfig(max_duration=int(args.duration), device=device_id)
    elif getattr(args, "silence_stop", False):
        config = AudioConfig(max_duration=600, device=device_id)
    else:
        config = AudioConfig(max_duration=300, device=device_id)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    wav_path = resolve_output_path(
        getattr(args, "output", None),
        f"recording_{timestamp}.wav",
    )

    if getattr(args, "silence_stop", False):
        audio = config.record_until_silence(progress_callback=progress_update)
    else:
        audio = config.record(
            duration=float(args.duration) if args.duration else None,
            progress_callback=progress_update,
        )

    if audio.size == 0:
        console.print("[red]No audio recorded![/red]")
        sys.exit(1)

    config.save_wav(audio, wav_path)
    console.print(f"[green]✓ Recorded to {wav_path}[/green]")
    return wav_path


def progress_update(fraction: float, status: str) -> None:
    console.print(f"  {status} ({fraction:.0%})")


def do_transcribe(args: argparse.Namespace) -> Transcript:
    """Transcribe an existing audio file (via session pipeline)."""
    result = cli_handlers.run_transcribe(args)
    # Build Transcript for display_results
    from diary_app.core.transcribe import Transcript as T
    transcript = T.from_json(result.transcript or {})
    kp = KeyPoints.from_json(result.key_points or {})
    display_results(args, transcript, kp, Path(result.wav_path) if result.wav_path else None)
    if getattr(args, "show_transcript", False) is False and result.warnings:
        pass
    return transcript


def do_analyze(args: argparse.Namespace) -> KeyPoints:
    """Analyze a transcript from a JSON file."""
    file_arg = getattr(args, "file", None)
    if not file_arg:
        # Default to latest transcript in diary dir
        candidates = sorted(DIARY_DIR.glob("transcript_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            console.print("[red]No transcript file given and none found in ~/diary[/red]")
            sys.exit(1)
        transcript_path = candidates[0]
    else:
        transcript_path = Path(file_arg).expanduser()

    if not transcript_path.exists():
        console.print(f"[red]Transcript file not found: {transcript_path}[/red]")
        sys.exit(1)

    console.print(Panel(f"🔍 Analyzing: {transcript_path}", style="bold cyan"))
    with open(transcript_path, encoding="utf-8") as f:
        data = json.load(f)

    transcript = Transcript.from_json(data)
    analyzer = TranscriptAnalyzer()
    key_points = analyzer.analyze(transcript)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = resolve_output_path(args.output, f"analysis_{ts}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({"key_points": key_points.to_json()}, f, indent=2)
    console.print(f"[green]✓ Key points saved to {save_path}[/green]")

    display_results(None, transcript, key_points, None)
    return key_points


def do_diary(args: argparse.Namespace) -> None:
    """Full diary workflow via session pipeline."""
    result = cli_handlers.run_diary(args)
    transcript = Transcript.from_json(result.transcript or {})
    kp = KeyPoints.from_json(result.key_points or {})
    display_results(args, transcript, kp, Path(result.wav_path) if result.wav_path else None)


def display_results(
    args,
    transcript: Transcript,
    key_points: KeyPoints,
    wav_path: Path | None,
) -> None:
    """Display transcript and analysis results."""
    console.print(Panel(
        f"[bold]📊 Results[/bold]\n"
        f"  Speakers: {len(transcript.speakers)}\n"
        f"  Duration: {transcript.duration:.0f}s\n"
        f"  Segments: {len(transcript.segments)}\n"
        f"  Output:   {wav_path or 'N/A'}",
        style="bold green",
    ))

    if key_points.speaker_stats:
        console.print(Panel(
            "[bold]👤 Speaker Statistics[/bold]\n" + "\n".join(
                f"  {speaker}: {stats['word_count']} words ({stats['percentage']}%), "
                f"{stats['duration_s']}s, {stats['segments']} segments"
                for speaker, stats in key_points.speaker_stats.items()
            ),
            style="cyan",
        ))

    if key_points.topics:
        console.print(Panel(
            "[bold]🏷 Topics[/bold]\n" + "\n".join(
                f"  • {topic}" for topic in key_points.topics
            ),
            style="yellow",
        ))

    if key_points.key_points:
        console.print(Panel(
            "[bold]📌 Key Points[/bold]\n" + "\n".join(
                f"  {i + 1}. {kp}" for i, kp in enumerate(key_points.key_points)
            ),
            style="blue",
        ))

    if getattr(key_points, "decisions", None):
        console.print(Panel(
            "[bold]✓ Decisions[/bold]\n" + "\n".join(
                f"  • {d}" for d in key_points.decisions
            ),
            style="magenta",
        ))

    if getattr(key_points, "action_items", None):
        console.print(Panel(
            "[bold]☐ Action items[/bold]\n" + "\n".join(
                f"  • {a}" for a in key_points.action_items
            ),
            style="bright_yellow",
        ))

    if key_points.takeaways:
        console.print(Panel(
            "[bold]✅ Takeaways[/bold]\n" + "\n".join(
                f"  {ta}" for ta in key_points.takeaways
            ),
            style="green",
        ))

    if args and getattr(args, "show_transcript", False):
        console.print(Panel(
            "[bold]📄 Full Transcript[/bold]\n\n" + transcript.format(),
            style="white",
        ))


def do_list(args: argparse.Namespace) -> None:
    """List history (recordings + transcripts), newest first."""
    from diary_app.core.history import list_entries, format_entry_summary, DEFAULT_DIARY_DIR
    from diary_app.core.speakers import filter_entries_by_person, display_speakers_for_entry

    root = Path(args.output).expanduser() if getattr(args, "output", None) else DEFAULT_DIARY_DIR
    limit = getattr(args, "limit", None) or 20
    person = getattr(args, "speaker", None) or getattr(args, "person", None)

    if person:
        entries = filter_entries_by_person(person, diary_dir=root, limit=limit)
        title = f"📚 History — speaker “{person}” ({len(entries)} shown)"
    else:
        entries = list_entries(root, limit=limit)
        title = f"📚 History ({len(entries)} shown) — {root}"

    if not entries:
        console.print("[yellow]No history entries found.[/yellow]")
        console.print(f"  Looking in: {root}")
        return

    console.print(Panel(f"[bold]{title}[/bold]", style="cyan"))
    for e in entries:
        audio_flag = "🔊" if e.has_audio else "  "
        tx_flag = "📝" if e.has_transcript else "  "
        who = ", ".join(display_speakers_for_entry(e, diary_dir=root)) or "—"
        console.print(
            f"  {audio_flag}{tx_flag} [bold]{e.id}[/bold]  {format_entry_summary(e)}"
        )
        console.print(f"       [cyan]speakers:[/] {who}")
        if e.preview:
            console.print(f"       [dim]{e.preview}[/dim]")


def do_history(args: argparse.Namespace) -> None:
    """Browse history: list, or show one entry (transcript + paths)."""
    from diary_app.core.history import (
        list_entries,
        get_entry,
        load_transcript_data,
        load_analysis_data,
        format_transcript_text,
        format_entry_summary,
        DEFAULT_DIARY_DIR,
    )
    from diary_app.core.speakers import (
        get_entry_speaker_map,
        set_entry_speaker_map,
        parse_rename_pairs,
        display_speakers_for_entry,
        raw_labels_from_transcript_data,
        SpeakerStore,
    )

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR
    entry_id = getattr(args, "id", None) or getattr(args, "entry", None)
    person = getattr(args, "speaker", None)

    # Rename on an entry without needing full view
    rename_pairs = getattr(args, "rename", None) or []
    if entry_id and rename_pairs:
        try:
            mapping = parse_rename_pairs(rename_pairs)
            clean = set_entry_speaker_map(
                entry_id,
                mapping,
                diary_dir=root,
                remember=bool(getattr(args, "remember", False)),
            )
            console.print(f"[green]✓ Renamed speakers on {entry_id}[/green]")
            for k, v in clean.items():
                console.print(f"  {k} → {v}")
            if getattr(args, "remember", False):
                console.print("[dim]Remembered as defaults for future sessions.[/dim]")
        except Exception as e:
            console.print(f"[red]Rename failed: {e}[/red]")
            sys.exit(1)
        if not getattr(args, "play", False) and not getattr(args, "show_only", False):
            # fall through to show the entry with new names
            pass

    if not entry_id:
        args.output = str(root)
        args.limit = getattr(args, "limit", 30) or 30
        args.speaker = person
        do_list(args)
        console.print(
            "\n[dim]View:[/]   python -m diary_app history --id <id>\n"
            "[dim]Rename:[/] python -m diary_app history --id <id> --rename 'Speaker 1=Alex' 'Speaker 2=Me'\n"
            "[dim]Remember defaults:[/] ... --rename ... --remember\n"
            "[dim]Filter:[/] python -m diary_app history --speaker Alex\n"
            "[dim]Play:[/]   python -m diary_app history --id <id> --play"
        )
        return

    entry = get_entry(entry_id, root)
    if not entry:
        console.print(f"[red]Entry not found: {entry_id}[/red]")
        matches = [e for e in list_entries(root, limit=50) if entry_id in e.id]
        if matches:
            console.print("Close matches:")
            for e in matches[:5]:
                console.print(f"  {e.id}")
        sys.exit(1)

    smap = get_entry_speaker_map(entry, root)
    who = ", ".join(display_speakers_for_entry(entry, diary_dir=root)) or "—"
    map_lines = "\n".join(f"    {k} → {v}" for k, v in smap.items()) if smap else "    (none yet)"

    tags_s = ", ".join(f"#{t}" for t in (entry.tags or [])) or "—"
    star = "★" if entry.starred else "—"
    console.print(Panel(
        f"[bold]📚 {entry.id}[/bold]\n"
        f"  When:       {entry.created_at}\n"
        f"  {format_entry_summary(entry)}\n"
        f"  Title:      {entry.title}\n"
        f"  Speakers:   {who}\n"
        f"  Tags:       {tags_s}\n"
        f"  Starred:    {star}\n"
        f"  Name map:\n{map_lines}\n"
        f"  Audio:      {entry.audio_path or '—'}\n"
        f"  Transcript: {entry.transcript_path or '—'}\n"
        f"  Analysis:   {entry.analysis_path or '—'}\n"
        f"  Backend:    {entry.backend or '—'}",
        style="bold green",
    ))
    if entry.notes:
        console.print(Panel(entry.notes, title="Notes", style="dim"))

    data = load_transcript_data(entry)
    if data:
        text = format_transcript_text(data, speaker_map=smap)
        if text:
            console.print(Panel(text, title="Transcript", style="white"))
        else:
            console.print("[yellow]Transcript file has no segments.[/yellow]")
        # Show raw labels for renaming help
        raw = raw_labels_from_transcript_data(data)
        if raw:
            store = SpeakerStore.load(root)
            suggestions = store.suggested_map(raw)
            sug = ", ".join(
                f"{r}→{suggestions[r]}" if r in suggestions else r for r in raw
            )
            console.print(f"[dim]Raw labels: {', '.join(raw)} | suggestions: {sug}[/dim]")
    else:
        console.print("[yellow]No transcript for this entry.[/yellow]")

    analysis = load_analysis_data(entry)
    if analysis:
        kp = analysis.get("key_points", analysis)
        if isinstance(kp, dict):
            lines = []
            if kp.get("summary"):
                lines.append(f"Summary: {kp['summary']}")
            for i, p in enumerate(kp.get("key_points") or [], 1):
                lines.append(f"  {i}. {p}")
            for t in kp.get("topics") or []:
                lines.append(f"  • {t}")
            if lines:
                console.print(Panel("\n".join(lines), title="Analysis", style="blue"))

    if getattr(args, "play", False):
        if not entry.has_audio:
            console.print("[red]No audio file available for this entry.[/red]")
            sys.exit(1)
        _play_audio(Path(entry.audio_path))


def do_speakers(args: argparse.Namespace) -> None:
    """Manage the known-people roster and global label defaults."""
    from diary_app.core.speakers import SpeakerStore
    from diary_app.core.history import DEFAULT_DIARY_DIR

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR
    store = SpeakerStore.load(root)
    action = getattr(args, "action", None) or "list"

    if action == "list":
        console.print(Panel(f"[bold]👥 Known people[/bold] — {root / 'speakers.json'}", style="cyan"))
        if not store.people:
            console.print("[yellow]No people yet. Add with:[/] python -m diary_app speakers add Alex")
        for p in sorted(store.people, key=lambda x: (-x.use_count, x.name.lower())):
            console.print(f"  • [bold]{p.name}[/bold]  (used {p.use_count}×, id={p.id})")
        if store.global_defaults:
            console.print("\n[bold]Remembered defaults[/bold] (applied to new sessions):")
            for k, v in store.global_defaults.items():
                console.print(f"  {k} → {v}")
        if store.recent_by_label:
            console.print("\n[bold]Recent label memory[/bold]:")
            for k, v in store.recent_by_label.items():
                console.print(f"  {k} → {v}")
        return

    if action == "add":
        name = getattr(args, "name", None)
        if not name:
            console.print("[red]Provide a name: speakers add Alex[/red]")
            sys.exit(1)
        p = store.add_person(name)
        console.print(f"[green]✓ Added person {p.name}[/green] ({p.id})")
        return

    if action == "remove":
        name = getattr(args, "name", None)
        if not name or not store.remove_person(name):
            console.print(f"[red]Could not remove: {name}[/red]")
            sys.exit(1)
        console.print(f"[green]✓ Removed {name}[/green]")
        return

    if action == "rename-person":
        old, new = getattr(args, "old_name", None), getattr(args, "new_name", None)
        if not old or not new:
            console.print("[red]Usage: speakers rename-person Old New[/red]")
            sys.exit(1)
        p = store.rename_person(old, new)
        console.print(f"[green]✓ Roster: {old} → {p.name}[/green]")
        return

    if action == "clear-defaults":
        store.global_defaults = {}
        store.save()
        console.print("[green]✓ Cleared global speaker defaults[/green]")
        return

    console.print(f"[red]Unknown speakers action: {action}[/red]")
    sys.exit(1)


def _play_audio(path: Path) -> None:
    """Play audio with a platform default player (best-effort)."""
    import subprocess
    import shutil

    path = Path(path)
    console.print(f"[cyan]Playing:[/] {path}")
    players = []
    if sys.platform == "darwin":
        players = [["afplay", str(path)], ["open", str(path)]]
    elif sys.platform.startswith("linux"):
        for cmd in ("ffplay", "aplay", "paplay", "mpv", "vlc", "xdg-open"):
            if shutil.which(cmd):
                if cmd == "ffplay":
                    players.append([cmd, "-nodisp", "-autoexit", str(path)])
                elif cmd == "aplay":
                    players.append([cmd, str(path)])
                else:
                    players.append([cmd, str(path)])
                break
    elif sys.platform == "win32":
        players = [["cmd", "/c", "start", "", str(path)]]

    if not players:
        console.print(
            f"[yellow]No audio player found. Open manually:[/]\n  {path}"
        )
        return

    try:
        subprocess.Popen(players[0])
        console.print("[green]Started system audio player.[/green]")
    except Exception as e:
        console.print(f"[red]Could not play audio: {e}[/red]")
        console.print(f"  File: {path}")


def do_search(args: argparse.Namespace) -> None:
    """Full-text search over diary history; show segment hits with seek times."""
    from diary_app.core.search import search_diary
    from diary_app.core.history import DEFAULT_DIARY_DIR, get_entry

    query = getattr(args, "query", None) or " ".join(getattr(args, "terms", []) or [])
    if not query and not getattr(args, "speaker", None):
        console.print("[red]Provide a search query or --speaker filter.[/red]")
        console.print("  python -m diary_app search budget")
        console.print("  python -m diary_app search \"next week\" --speaker Alex")
        sys.exit(1)

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR
    limit = getattr(args, "limit", None) or 20
    person = getattr(args, "speaker", None)

    hits = search_diary(
        query or "",
        diary_dir=root,
        person=person,
        limit=limit,
    )
    if not hits:
        console.print("[yellow]No matches.[/yellow]")
        return

    title = f"Search: {query!r}" if query else "Search"
    if person:
        title += f" · speaker={person}"
    console.print(Panel(f"[bold]🔎 {title}[/bold] — {len(hits)} entries", style="cyan"))

    for h in hits:
        audio_flag = "🔊" if h.has_audio else "  "
        console.print(
            f"\n{audio_flag} [bold]{h.entry_id}[/bold]  "
            f"score={h.score:.2f}  {h.created_at}  "
            f"[{', '.join(h.speakers) or '—'}]"
        )
        if h.title:
            console.print(f"   [dim]{h.title[:100]}[/dim]")
        console.print(f"   matched: {', '.join(h.match_fields)}")
        for seg in h.segments[:5]:
            console.print(
                f"   [{seg.start:6.1f}s–{seg.end:5.1f}s] "
                f"[cyan]{seg.speaker}[/]: {seg.snippet}"
            )
        if len(h.segments) > 5:
            console.print(f"   [dim]… +{len(h.segments) - 5} more segments[/dim]")

    # Optional: open first hit
    open_id = getattr(args, "open", None)
    if open_id is True:
        open_id = hits[0].entry_id if hits else None
    if open_id:
        # reuse history view
        class _NS:
            pass
        ns = _NS()
        ns.id = open_id if isinstance(open_id, str) else hits[0].entry_id
        ns.dir = str(root)
        ns.rename = None
        ns.remember = False
        ns.play = bool(getattr(args, "play", False))
        ns.speaker = None
        ns.limit = 30
        ns.entry = None
        do_history(ns)

    if getattr(args, "seek", False) and hits:
        # play first audio hit starting at first segment (best-effort with ffplay -ss)
        target = None
        start = 0.0
        for h in hits:
            if h.has_audio and h.audio_path:
                target = h.audio_path
                if h.segments:
                    start = h.segments[0].start
                break
        if target:
            _play_audio_at(Path(target), start)
        else:
            console.print("[yellow]No audio available to seek.[/yellow]")


def _play_audio_at(path: Path, start_s: float = 0.0) -> None:
    """Play audio from a timestamp when possible (ffplay/mpv)."""
    import subprocess
    import shutil

    path = Path(path)
    console.print(f"[cyan]Playing from {start_s:.1f}s:[/] {path}")
    if shutil.which("ffplay"):
        subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-ss", str(start_s), str(path)]
        )
        console.print("[green]Started ffplay.[/green]")
        return
    if shutil.which("mpv"):
        subprocess.Popen(["mpv", f"--start={start_s}", str(path)])
        console.print("[green]Started mpv.[/green]")
        return
    # fallback full play
    _play_audio(path)


def do_actions(args: argparse.Namespace) -> None:
    """Global action-item inbox: sync from analyses, list, complete."""
    from diary_app.core.actions import ActionInbox
    from diary_app.core.history import DEFAULT_DIARY_DIR

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR
    box = ActionInbox(root)
    action = getattr(args, "action", None) or "list"

    if action == "sync":
        n = box.sync_from_history()
        console.print(f"[green]✓ Synced {n} new action item(s) from history[/green]")
        action = "list"

    if action == "list":
        if getattr(args, "sync", True):
            box.sync_from_history()
        include_done = bool(getattr(args, "all", False))
        items = box.list_items(include_done=include_done)
        open_n = len([i for i in box.items.values() if not i.done])
        done_n = len([i for i in box.items.values() if i.done])
        console.print(Panel(
            f"[bold]☐ Action inbox[/bold]  open={open_n}  done={done_n}",
            style="cyan",
        ))
        if not items:
            console.print("[yellow]No open actions. Run after transcribe, or: actions sync[/yellow]")
            return
        for it in items:
            mark = "✓" if it.done else "☐"
            console.print(f"  {mark} [bold]{it.id}[/bold]  {it.text}")
            console.print(f"      [dim]entry={it.entry_id or '—'}  {it.created_at}[/dim]")
        return

    if action == "done":
        aid = getattr(args, "id", None) or getattr(args, "item", None)
        if not aid:
            console.print("[red]Provide --id for the action[/red]")
            sys.exit(1)
        try:
            it = box.mark_done(aid, done=True)
            console.print(f"[green]✓ Done:[/] {it.text}")
        except Exception as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)
        return

    if action == "undo":
        aid = getattr(args, "id", None) or getattr(args, "item", None)
        if not aid:
            console.print("[red]Provide --id[/red]")
            sys.exit(1)
        it = box.mark_done(aid, done=False)
        console.print(f"[yellow]Reopened:[/] {it.text}")
        return

    if action == "add":
        text = getattr(args, "text", None) or " ".join(getattr(args, "words", []) or [])
        if not text:
            console.print("[red]Provide action text[/red]")
            sys.exit(1)
        it = box.add_manual(text, entry_id=getattr(args, "entry", None) or "")
        console.print(f"[green]✓ Added {it.id}:[/] {it.text}")
        return

    if action == "remove":
        aid = getattr(args, "id", None)
        box.remove(aid)
        console.print(f"[green]✓ Removed {aid}[/green]")
        return

    console.print(f"[red]Unknown actions command: {action}[/red]")
    sys.exit(1)


def do_tag(args: argparse.Namespace) -> None:
    """Add/remove tags, notes, or star an entry."""
    from diary_app.core.annotate import update_entry_annotation, list_all_tags, filter_entries
    from diary_app.core.history import DEFAULT_DIARY_DIR, format_entry_summary

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR

    if getattr(args, "list_tags", False):
        tags = list_all_tags(root)
        if not tags:
            console.print("[yellow]No tags yet.[/yellow]")
            return
        for t in tags:
            console.print(f"  #{t['tag']}  ({t['count']})")
        return

    entry_id = getattr(args, "id", None)
    if not entry_id and getattr(args, "tag_filter", None):
        entries = filter_entries(diary_dir=root, tag=args.tag_filter, starred=None, limit=50)
        console.print(Panel(f"[bold]#{args.tag_filter}[/bold] — {len(entries)} entries", style="cyan"))
        for e in entries:
            star = "★" if e.starred else " "
            console.print(f"  {star} {e.id}  {format_entry_summary(e)}")
            if e.tags:
                console.print(f"      tags: {', '.join('#'+t for t in e.tags)}")
        return

    if not entry_id and getattr(args, "starred_only", False):
        entries = filter_entries(diary_dir=root, starred=True, limit=50)
        console.print(Panel(f"[bold]★ Starred[/bold] — {len(entries)}", style="yellow"))
        for e in entries:
            console.print(f"  ★ {e.id}  {e.title or e.preview[:60]}")
        return

    if not entry_id:
        console.print("[red]Provide --id <entry> or --list-tags / --filter-tag / --starred[/red]")
        sys.exit(1)

    try:
        e = update_entry_annotation(
            entry_id,
            diary_dir=root,
            add_tags=getattr(args, "add", None),
            remove_tags=getattr(args, "remove", None),
            notes=getattr(args, "notes", None),
            append_note=getattr(args, "note", None),
            starred=True if getattr(args, "star", False) else (False if getattr(args, "unstar", False) else None),
        )
    except Exception as ex:
        console.print(f"[red]{ex}[/red]")
        sys.exit(1)

    console.print(f"[green]✓ Updated {e.id}[/green]")
    console.print(f"  tags: {', '.join('#'+t for t in (e.tags or [])) or '—'}")
    console.print(f"  starred: {e.starred}")
    if e.notes:
        console.print(f"  notes:\n{e.notes}")


def do_export(args: argparse.Namespace) -> None:
    """Export a history entry to Markdown / SRT / TXT / JSON."""
    from diary_app.core.export import export_entry
    from diary_app.core.history import DEFAULT_DIARY_DIR, list_entries

    entry_id = getattr(args, "id", None) or getattr(args, "entry", None)
    if not entry_id:
        # latest entry
        entries = list_entries(DEFAULT_DIARY_DIR, limit=1)
        if not entries:
            console.print("[red]No entries to export.[/red]")
            sys.exit(1)
        entry_id = entries[0].id
        console.print(f"[dim]No --id given; exporting latest {entry_id}[/dim]")

    formats = getattr(args, "formats", None) or ["md", "srt", "txt", "json"]
    if isinstance(formats, str):
        formats = [f.strip() for f in formats.split(",") if f.strip()]
    out_dir = Path(args.output).expanduser() if getattr(args, "output", None) else None
    try:
        result = export_entry(entry_id, out_dir=out_dir, formats=formats)
    except Exception as e:
        console.print(f"[red]Export failed: {e}[/red]")
        sys.exit(1)

    console.print(Panel(
        f"[bold]📦 Export {result.entry_id}[/bold]\n"
        f"  dir: {result.out_dir}\n"
        + "\n".join(f"  • {f}" for f in result.files),
        style="green",
    ))


def do_digest(args: argparse.Namespace) -> None:
    """Build a daily/weekly digest of sessions, actions, and decisions."""
    from diary_app.core.digest import digests_for_range, digest_to_markdown, write_digest
    from diary_app.core.history import DEFAULT_DIARY_DIR

    days = getattr(args, "days", None)
    start = getattr(args, "start", None)
    end = getattr(args, "end", None)
    if days is None and not start and not end:
        days = 7

    digests = digests_for_range(days=days, start=start, end=end)
    md = digest_to_markdown(digests)
    console.print(md)

    if getattr(args, "save", True) is not False or getattr(args, "output", None):
        fmt = getattr(args, "format", None) or "md"
        out = write_digest(
            days=days or 7,
            start=start,
            end=end,
            fmt=fmt if fmt in ("md", "json") else "md",
            out_path=Path(args.output).expanduser() if getattr(args, "output", None) else None,
        )
        console.print(f"\n[green]✓ Digest saved to {out}[/green]")


def do_devices(_args: argparse.Namespace) -> None:
    """Print GPU/CPU detection report."""
    from diary_app.core.device import format_detect_report, resolve_torch_device
    console.print(Panel(format_detect_report(), title="GPU / device detection", style="cyan"))
    try:
        info = resolve_torch_device("auto")
        console.print(f"[bold green]auto would select:[/] {info.details}")
    except Exception as e:
        console.print(f"[yellow]Could not resolve auto device: {e}[/]")


def do_doctor(_args: argparse.Namespace) -> None:
    """Multi-arch install health check (OS, arch, torch wheels, imports)."""
    from diary_app.core.platform_info import format_doctor_report, doctor_checks

    report = format_doctor_report()
    console.print(Panel(report, title="Omniflow doctor", style="cyan"))
    data = doctor_checks()
    if not data.get("ok"):
        console.print(
            "[yellow]Fix install with:[/]\n"
            "  python -m diary_app.install_torch\n"
            "  bash diary_app/setup_venv.sh\n"
            "  # force CPU:  OMNIFLOW_TORCH=cpu bash diary_app/setup_venv.sh\n"
            "  # force CUDA: OMNIFLOW_TORCH=cuda bash diary_app/setup_venv.sh"
        )
        sys.exit(1)


def do_config(args: argparse.Namespace) -> None:
    """Show or write application config."""
    cfg = get_config()
    action = getattr(args, "action", None) or "show"
    if action == "write-example":
        path = write_example_config(
            Path(args.path).expanduser() if getattr(args, "path", None) else None
        )
        console.print(f"[green]✓ Wrote example config to {path}[/green]")
        return
    if action == "path":
        from diary_app.config import _default_config_paths

        for p in _default_config_paths():
            mark = " (exists)" if p.is_file() else ""
            console.print(f"  {p}{mark}")
        return
    console.print(Panel(json.dumps(cfg.to_dict(), indent=2), title="AppConfig", style="cyan"))


def _add_backend_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        choices=list(BACKEND_CHOICES),
        default="auto",
        help="Backend: moss (default Mac+PC model), whisper, nemo, or auto",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Compute device: auto (CUDA→MPS→CPU), cuda, cuda:0, mps, or cpu",
    )
    parser.add_argument(
        "--mps",
        action="store_true",
        help="Prefer larger whisper model when using whisper backend",
    )
    parser.add_argument(
        "--show-transcript",
        action="store_true",
        help="Show full transcript in results",
    )


def do_api(args: argparse.Namespace) -> None:
    """JSON IPC — see diary_app.core.api."""
    from diary_app.core.api import run_api_argv

    # Reconstruct remaining argv after 'api'
    rest = list(getattr(args, "api_argv", None) or [])
    code = run_api_argv(rest)
    sys.exit(code)


def do_serve(args: argparse.Namespace) -> None:
    """Long-lived localhost daemon (product IPC for Tauri)."""
    from diary_app.core.daemon import run_serve_argv

    # Rebuild argv for the serve parser
    argv: list[str] = []
    if getattr(args, "host", None):
        argv.extend(["--host", str(args.host)])
    if getattr(args, "port", None) is not None:
        argv.extend(["--port", str(args.port)])
    if getattr(args, "detach", False):
        argv.append("--detach")
    if getattr(args, "token", None):
        argv.extend(["--token", str(args.token)])
    if getattr(args, "dir", None):
        argv.extend(["--dir", str(args.dir)])
    if getattr(args, "replace", False):
        argv.append("--replace")
    sys.exit(run_serve_argv(argv))


def do_daemon(args: argparse.Namespace) -> None:
    """daemon status | stop | ensure | ping"""
    from diary_app.core.daemon import daemon_status, stop_daemon, diary_root
    from diary_app.core.daemon_client import ensure_daemon, DaemonClient, DaemonError

    action = getattr(args, "action", None) or "status"
    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else diary_root()

    if action == "status":
        data = daemon_status(root)
        console.print_json(data=data)
        return
    if action == "stop":
        data = stop_daemon(root=root)
        console.print_json(data=data)
        return
    if action == "ping":
        from diary_app.core.daemon import read_state

        st = read_state(root)
        if not st:
            console.print("[red]No daemon state[/red]")
            sys.exit(1)
        try:
            ok = DaemonClient.from_state(st).ping()
        except DaemonError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)
        console.print("[green]pong[/green]" if ok else "[red]no response[/red]")
        sys.exit(0 if ok else 1)
    if action == "ensure":
        try:
            client = ensure_daemon(
                project_root=Path(__file__).resolve().parents[2],
            )
            st = {
                "host": client.host,
                "port": client.port,
                "alive": True,
            }
            console.print_json(data={"ok": True, **st})
        except Exception as e:
            console.print(f"[red]ensure failed: {e}[/red]")
            sys.exit(1)
        return
    console.print(f"[red]Unknown daemon action: {action}[/red]")
    sys.exit(1)


def do_archive(args: argparse.Namespace) -> None:
    from diary_app.core.history import archive_entry, DEFAULT_DIARY_DIR

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR
    eid = args.id
    if not eid:
        console.print("[red]--id required[/red]")
        sys.exit(1)
    try:
        e = archive_entry(eid, diary_dir=root, unarchive=bool(getattr(args, "unarchive", False)))
    except Exception as ex:
        console.print(f"[red]{ex}[/red]")
        sys.exit(1)
    state = "restored" if getattr(args, "unarchive", False) else "archived"
    console.print(f"[green]✓ Entry {e.id} {state}[/green]")


def do_delete(args: argparse.Namespace) -> None:
    from diary_app.core.history import delete_entry, DEFAULT_DIARY_DIR

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR
    eid = args.id
    if not eid:
        console.print("[red]--id required[/red]")
        sys.exit(1)
    if not getattr(args, "yes", False):
        console.print(f"[yellow]Delete entry {eid}? Pass --yes to confirm.[/yellow]")
        sys.exit(1)
    try:
        result = delete_entry(
            eid,
            diary_dir=root,
            delete_audio=bool(getattr(args, "delete_audio", False)),
        )
    except Exception as ex:
        console.print(f"[red]{ex}[/red]")
        sys.exit(1)
    console.print(f"[green]✓ Deleted {result['id']}[/green]")
    for p in result.get("removed") or []:
        console.print(f"  - {p}")


def do_reindex(args: argparse.Namespace) -> None:
    from diary_app.core.index_db import rebuild_index
    from diary_app.core.history import DEFAULT_DIARY_DIR

    root = Path(args.dir).expanduser() if getattr(args, "dir", None) else DEFAULT_DIARY_DIR
    n = rebuild_index(root)
    console.print(f"[green]✓ Indexed {n} entries → {root / 'index.sqlite'}[/green]")



def get_command_handlers() -> dict:
    """Name → callable for subcommands."""
    return {
        "diary": do_diary,
        "record": do_record,
        "transcribe": do_transcribe,
        "analyze": do_analyze,
        "list": do_list,
        "history": do_history,
        "speakers": do_speakers,
        "search": do_search,
        "export": do_export,
        "digest": do_digest,
        "tag": do_tag,
        "actions": do_actions,
        "devices": do_devices,
        "doctor": do_doctor,
        "config": do_config,
        "serve": do_serve,
        "daemon": do_daemon,
        "archive": do_archive,
        "delete": do_delete,
        "reindex": do_reindex,
        "api": do_api,
    }
