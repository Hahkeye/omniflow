"""History / speakers / search CLI commands."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.panel import Panel

from diary_app.cli.common import console


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


