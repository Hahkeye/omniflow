"""Argparse construction for diary_app CLI."""
from __future__ import annotations

import argparse

from diary_app.cli.commands import BACKEND_CHOICES, _add_backend_args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
    description="Diary Transcript — record, transcribe multi-speaker audio, and analyze",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
    Examples:
      python -m diary_app diary
      python -m diary_app transcribe recording.wav --backend moss
      python -m diary_app history
      python -m diary_app history --id 20260709_181713
      python -m diary_app history --id 20260709_181713 --rename 'Speaker 1=Alex' --remember
      python -m diary_app history --speaker Alex
      python -m diary_app search budget
      python -m diary_app export --id 20260709_181713
      python -m diary_app digest --days 7
      python -m diary_app tag --id 20260709_181713 --add meeting --star
      python -m diary_app actions list
      python -m diary_app actions done a_abc123
      python -m diary_app archive --id 20260709_181713_a1b2c3
      python -m diary_app delete --id 20260709_181713_a1b2c3 --yes
      python -m diary_app reindex
      python -m diary_app api history_list --set limit=10
      python -m diary_app devices
      python -m diary_app doctor
      python -m diary_app serve --detach
      python -m diary_app daemon status
      python -m diary_app daemon stop
      python -m diary_app.install_torch --dry-run
    """,
    )

    subparsers = parser.add_subparsers(dest="command")

    diary = subparsers.add_parser("diary", help="Record + transcribe + analyze")
    _add_backend_args(diary)
    diary.add_argument("--duration", type=int, default=None, help="Recording duration (seconds)")
    diary.add_argument("--silence-stop", action="store_true", help="Stop after silence")
    diary.add_argument("--output", type=str, default=None, help="Output file or directory")
    diary.add_argument("--file", type=str, default=None, help="Audio file (skip recording)")

    record = subparsers.add_parser("record", help="Record audio from microphone")
    record.add_argument("--duration", type=int, default=None, help="Recording duration (seconds)")
    record.add_argument("--silence-stop", action="store_true", help="Stop after silence")
    record.add_argument("--output", type=str, default=None, help="Output file or directory")

    transcribe = subparsers.add_parser("transcribe", help="Transcribe an existing audio file")
    transcribe.add_argument("file", help="Audio file to transcribe")
    _add_backend_args(transcribe)
    transcribe.add_argument("--output", type=str, default=None, help="Output file or directory")

    analyze = subparsers.add_parser("analyze", help="Analyze a transcript JSON")
    analyze.add_argument("--file", help="Transcript JSON file (default: latest in ~/diary)")
    analyze.add_argument("--output", type=str, default=None, help="Output file or directory")

    list_p = subparsers.add_parser("list", help="List recent history (alias for history)")
    list_p.add_argument("--output", type=str, default=None, help="Diary directory")
    list_p.add_argument("--limit", type=int, default=20, help="Max entries to show")
    list_p.add_argument("--speaker", "--person", dest="speaker", default=None, help="Filter by person name")

    history_p = subparsers.add_parser(
    "history",
    help="Browse past recordings/transcripts; rename speakers; filter by person",
    )
    history_p.add_argument("--id", "--entry", dest="id", default=None, help="Entry id to open")
    history_p.add_argument("--dir", type=str, default=None, help="Diary directory (default ~/diary)")
    history_p.add_argument("--limit", type=int, default=30, help="Max entries when listing")
    history_p.add_argument("--speaker", "--person", dest="speaker", default=None, help="Filter list by person")
    history_p.add_argument(
    "--rename",
    nargs="+",
    default=None,
    help="Rename speakers on --id entry: 'Speaker 1=Alex' 'Speaker 2=Me'",
    )
    history_p.add_argument(
    "--remember",
    action="store_true",
    help="With --rename, also remember as defaults for future sessions",
    )
    history_p.add_argument(
    "--play",
    action="store_true",
    help="Play the entry audio with a system player",
    )

    speakers_p = subparsers.add_parser("speakers", help="Manage known people / speaker memory")
    speakers_sub = speakers_p.add_subparsers(dest="action")
    speakers_p.add_argument("--dir", type=str, default=None, help="Diary directory")
    speakers_sub.add_parser("list", help="List known people and defaults")
    sp_add = speakers_sub.add_parser("add", help="Add a person to the roster")
    sp_add.add_argument("name", help="Display name")
    sp_rm = speakers_sub.add_parser("remove", help="Remove a person from the roster")
    sp_rm.add_argument("name", help="Display name")
    sp_ren = speakers_sub.add_parser("rename-person", help="Rename someone in the roster")
    sp_ren.add_argument("old_name")
    sp_ren.add_argument("new_name")
    speakers_sub.add_parser("clear-defaults", help="Clear remembered Speaker N → name defaults")

    search_p = subparsers.add_parser(
    "search",
    help="Full-text search history; shows segment times for audio seek",
    )
    search_p.add_argument("terms", nargs="*", help="Search terms (or use --query)")
    search_p.add_argument("--query", "-q", default=None, help="Search query string")
    search_p.add_argument("--speaker", "--person", dest="speaker", default=None, help="Filter by person")
    search_p.add_argument("--limit", type=int, default=20)
    search_p.add_argument("--dir", type=str, default=None)
    search_p.add_argument(
    "--open",
    nargs="?",
    const=True,
    default=None,
    help="Open first (or given) matching entry in history view",
    )
    search_p.add_argument(
    "--seek",
    action="store_true",
    help="Play first matching audio from first hit timestamp (ffplay/mpv)",
    )
    search_p.add_argument("--play", action="store_true", help="With --open, also play audio")

    export_p = subparsers.add_parser(
    "export",
    help="Export an entry to Markdown, SRT, TXT, and/or JSON",
    )
    export_p.add_argument("--id", "--entry", dest="id", default=None, help="Entry id (default: latest)")
    export_p.add_argument(
    "--formats",
    default="md,srt,txt,json",
    help="Comma-separated: md,srt,txt,json",
    )
    export_p.add_argument("--output", type=str, default=None, help="Output directory")

    digest_p = subparsers.add_parser(
    "digest",
    help="Daily/weekly rollup of sessions, decisions, and action items",
    )
    digest_p.add_argument("--days", type=int, default=None, help="Last N active days (default 7)")
    digest_p.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD")
    digest_p.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD")
    digest_p.add_argument("--output", type=str, default=None, help="Write digest file path")
    digest_p.add_argument("--format", choices=["md", "json"], default="md")
    digest_p.add_argument(
    "--no-save",
    dest="save",
    action="store_false",
    help="Print only; do not write ~/diary/exports/",
    )

    tag_p = subparsers.add_parser(
    "tag",
    help="Tag, note, or star history entries; list tags",
    )
    tag_p.add_argument("--id", dest="id", default=None, help="Entry id")
    tag_p.add_argument("--dir", type=str, default=None)
    tag_p.add_argument("--add", nargs="+", default=None, help="Tags to add")
    tag_p.add_argument("--remove", nargs="+", default=None, help="Tags to remove")
    tag_p.add_argument("--note", type=str, default=None, help="Append a timestamped note")
    tag_p.add_argument("--notes", type=str, default=None, help="Replace notes entirely")
    tag_p.add_argument("--star", action="store_true", help="Star entry")
    tag_p.add_argument("--unstar", action="store_true", help="Remove star")
    tag_p.add_argument("--list-tags", action="store_true", help="List all tags")
    tag_p.add_argument("--filter-tag", dest="tag_filter", default=None, help="List entries with tag")
    tag_p.add_argument("--starred", dest="starred_only", action="store_true", help="List starred entries")

    actions_p = subparsers.add_parser(
    "actions",
    help="Action-item inbox across sessions (list / done / add)",
    )
    actions_p.add_argument("--dir", type=str, default=None)
    actions_sub = actions_p.add_subparsers(dest="action")
    act_list = actions_sub.add_parser("list", help="List open actions (syncs from history)")
    act_list.add_argument("--all", action="store_true", help="Include completed")
    act_list.add_argument("--no-sync", dest="sync", action="store_false")
    actions_sub.add_parser("sync", help="Pull new items from analysis files")
    act_done = actions_sub.add_parser("done", help="Mark action complete")
    act_done.add_argument("id", help="Action id (or unique prefix)")
    act_undo = actions_sub.add_parser("undo", help="Reopen a completed action")
    act_undo.add_argument("id")
    act_add = actions_sub.add_parser("add", help="Add a manual action item")
    act_add.add_argument("words", nargs="+", help="Action text")
    act_add.add_argument("--entry", default="", help="Optional entry id")
    act_rm = actions_sub.add_parser("remove", help="Delete an action")
    act_rm.add_argument("id")

    subparsers.add_parser(
    "devices",
    help="Show GPU/CPU detection (CUDA / MPS / CPU) and what auto would pick",
    )
    subparsers.add_parser(
    "doctor",
    help="Multi-arch install health check (OS, arch, torch wheels, imports)",
    )

    config_p = subparsers.add_parser(
    "config",
    help="Show AppConfig or write example ~/.config/omniflow/config.toml",
    )
    config_p.add_argument(
    "action",
    nargs="?",
    default="show",
    choices=["show", "write-example", "path"],
    )
    config_p.add_argument("--path", default=None, help="Path for write-example")

    serve_p = subparsers.add_parser(
    "serve",
    help="Start long-lived localhost daemon (NDJSON TCP; keeps models warm)",
    )
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=17432)
    serve_p.add_argument("--detach", "-d", action="store_true")
    serve_p.add_argument("--token", default=None)
    serve_p.add_argument("--dir", default=None)
    serve_p.add_argument("--replace", action="store_true")

    daemon_p = subparsers.add_parser(
    "daemon",
    help="Control the local daemon: status | stop | ping | ensure",
    )
    daemon_p.add_argument(
    "action",
    nargs="?",
    default="status",
    choices=["status", "stop", "ping", "ensure"],
    )
    daemon_p.add_argument("--dir", default=None)

    archive_p = subparsers.add_parser("archive", help="Archive (hide) a history entry")
    archive_p.add_argument("--id", required=True, help="Entry id")
    archive_p.add_argument("--dir", type=str, default=None)
    archive_p.add_argument("--unarchive", action="store_true", help="Restore from archive")

    delete_p = subparsers.add_parser("delete", help="Permanently delete a history entry")
    delete_p.add_argument("--id", required=True, help="Entry id")
    delete_p.add_argument("--dir", type=str, default=None)
    delete_p.add_argument("--yes", action="store_true", help="Confirm deletion")
    delete_p.add_argument(
    "--delete-audio",
    action="store_true",
    help="Also delete audio if it lives under the diary directory",
    )

    reindex_p = subparsers.add_parser(
    "reindex",
    help="Rebuild SQLite FTS index under ~/diary/index.sqlite",
    )
    reindex_p.add_argument("--dir", type=str, default=None)

    # api is handled via fast path above; keep a help stub
    subparsers.add_parser(
    "api",
    help="JSON IPC for UIs: diary_app api <command> [--json '{...}']",
    )


    return parser
