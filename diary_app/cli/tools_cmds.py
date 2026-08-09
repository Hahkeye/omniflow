"""Utility CLI commands: actions, tags, export, digest, config, daemon."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.panel import Panel

from diary_app.cli.common import console
from diary_app.config import get_config, write_example_config

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



