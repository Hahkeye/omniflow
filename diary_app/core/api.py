"""
JSON IPC surface for UIs (Tauri, scripts).

Usage:
  python -m diary_app api <command> [--json '{"..."}']
  echo '{"command":"history_list","limit":10}' | python -m diary_app api

Every response is a single JSON object on stdout:
  {"ok": true, ...} or {"ok": false, "error": "..."}

Progress events (long jobs) are printed on stderr as:
  PROGRESS_JSON {...}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .logutil import ensure_logging, get_logger

log = get_logger("api")


def _ok(**kwargs: Any) -> dict[str, Any]:
    out = {"ok": True}
    out.update(kwargs)
    return out


def _err(message: str, **kwargs: Any) -> dict[str, Any]:
    out = {"ok": False, "error": str(message)}
    out.update(kwargs)
    return out


def _diary_dir(params: dict) -> Path:
    from diary_app.config import get_config

    d = params.get("diary_dir") or params.get("dir")
    return Path(d).expanduser() if d else Path(get_config().diary_dir)


def cmd_history_list(params: dict) -> dict:
    from .history import entries_for_api

    limit = int(params.get("limit") or 100)
    person = params.get("person") or params.get("speaker") or None
    include_archived = bool(params.get("include_archived"))
    # entries_for_api uses list_entries; pass person only
    entries = entries_for_api(
        root=_diary_dir(params),
        limit=limit,
        person=person,
    )
    if include_archived:
        from .history import list_entries

        # rebuild with archived
        from .speakers import display_speakers_for_entry, get_entry_speaker_map

        root = _diary_dir(params)
        raw = list_entries(root, limit=limit, include_archived=True)
        entries = []
        for e in raw:
            d = e.to_dict()
            d["has_audio"] = e.has_audio
            d["has_transcript"] = e.has_transcript
            d["display_speakers"] = display_speakers_for_entry(e, diary_dir=root)
            d["speaker_map"] = get_entry_speaker_map(e, root) or {}
            entries.append(d)
    return _ok(entries=entries)


def cmd_history_get(params: dict) -> dict:
    from .history import (
        get_entry,
        load_transcript_data,
        load_analysis_data,
        format_transcript_text,
    )
    from .speakers import (
        get_entry_speaker_map,
        display_speakers_for_entry,
        raw_labels_from_transcript_data,
    )
    from .search import get_entry_segments

    eid = params.get("entry_id") or params.get("id")
    if not eid:
        return _err("entry_id required")
    root = _diary_dir(params)
    e = get_entry(str(eid), root)
    if not e:
        return _err(f"not found: {eid}")
    tx = load_transcript_data(e)
    an = load_analysis_data(e)
    smap = get_entry_speaker_map(e, root)
    kp = an.get("key_points", an) if an else {}
    analysis_lines = []
    if isinstance(kp, dict):
        if kp.get("summary"):
            analysis_lines.append("Summary: " + kp["summary"])
        for i, p in enumerate(kp.get("key_points") or [], 1):
            analysis_lines.append(f"{i}. {p}")
        for t in kp.get("topics") or []:
            analysis_lines.append(f"• {t}")
        for d in kp.get("decisions") or []:
            analysis_lines.append(f"✓ {d}")
        for a in kp.get("action_items") or []:
            analysis_lines.append(f"☐ {a}")
    ed = e.to_dict()
    ed["display_speakers"] = display_speakers_for_entry(e, diary_dir=root)
    ed["speaker_map"] = smap
    ed["raw_labels"] = raw_labels_from_transcript_data(tx) if tx else []
    return _ok(
        entry=ed,
        transcript_text=format_transcript_text(tx, speaker_map=smap) if tx else "",
        analysis_text="\n".join(analysis_lines),
        audio_path=e.audio_path if e.has_audio else None,
        segments=get_entry_segments(e.id, diary_dir=root),
    )


def cmd_search(params: dict) -> dict:
    from .search import search_for_api

    query = params.get("query") or ""
    person = params.get("person") or params.get("speaker")
    limit = int(params.get("limit") or 50)
    hits = search_for_api(
        query,
        person=person,
        limit=limit,
        diary_dir=_diary_dir(params),
    )
    return _ok(hits=hits)


def cmd_speakers_rename(params: dict) -> dict:
    from .speakers import set_entry_speaker_map

    eid = params.get("entry_id") or params.get("id")
    mapping = params.get("mapping") or {}
    if isinstance(mapping, str):
        mapping = json.loads(mapping)
    if not eid:
        return _err("entry_id required")
    remember = params.get("remember", True)
    if isinstance(remember, str):
        remember = remember not in ("0", "false", "False")
    clean = set_entry_speaker_map(
        str(eid),
        mapping,
        diary_dir=_diary_dir(params),
        remember=bool(remember),
    )
    return _ok(speaker_map=clean)


def cmd_speakers_roster(params: dict) -> dict:
    from .speakers import roster_for_api

    return _ok(roster=roster_for_api(diary_dir=_diary_dir(params)))


def cmd_export(params: dict) -> dict:
    from .export import export_for_api

    eid = params.get("entry_id") or params.get("id")
    if not eid:
        return _err("entry_id required")
    formats = params.get("formats") or "md,srt,txt,json"
    if isinstance(formats, str):
        formats = [f.strip() for f in formats.split(",") if f.strip()]
    result = export_for_api(str(eid), formats=formats, diary_dir=_diary_dir(params))
    if isinstance(result, dict):
        return _ok(**result)
    return _ok(result=result)


def cmd_digest(params: dict) -> dict:
    from .digest import digests_for_api, write_digest

    days = int(params.get("days") or 7)
    data = digests_for_api(days=days, diary_dir=_diary_dir(params))
    path = str(write_digest(days=days, fmt="md", diary_dir=_diary_dir(params)))
    return _ok(
        markdown=data.get("markdown", ""),
        path=path,
        days=data.get("days", []),
    )


def cmd_actions_inbox(params: dict) -> dict:
    from .actions import inbox_for_api

    include_done = bool(params.get("include_done"))
    sync = params.get("sync", True)
    if isinstance(sync, str):
        sync = sync not in ("0", "false")
    data = inbox_for_api(
        include_done=include_done,
        sync=bool(sync),
        diary_dir=_diary_dir(params),
    )
    return _ok(**data) if isinstance(data, dict) else _ok(inbox=data)


def cmd_actions_done(params: dict) -> dict:
    from .actions import ActionInbox

    aid = params.get("action_id") or params.get("id")
    if not aid:
        return _err("action_id required")
    done = params.get("done", True)
    if isinstance(done, str):
        done = done not in ("0", "false")
    it = ActionInbox(_diary_dir(params)).mark_done(str(aid), done=bool(done))
    return _ok(item=it.to_dict())


def cmd_entry_annotate(params: dict) -> dict:
    from .annotate import update_entry_annotation

    eid = params.get("entry_id") or params.get("id")
    if not eid:
        return _err("entry_id required")
    tags = params.get("add_tags") or params.get("tags")
    if isinstance(tags, str):
        tags = [t for t in tags.replace(",", " ").split() if t]
    star = params.get("star")
    if isinstance(star, str):
        star = None if star == "" else star in ("1", "true", "True")
    e = update_entry_annotation(
        str(eid),
        diary_dir=_diary_dir(params),
        add_tags=tags,
        append_note=params.get("note") or params.get("append_note"),
        starred=star,
    )
    return _ok(entry=e.to_dict())


def cmd_entry_archive(params: dict) -> dict:
    from .history import archive_entry

    eid = params.get("entry_id") or params.get("id")
    if not eid:
        return _err("entry_id required")
    unarchive = bool(params.get("unarchive"))
    e = archive_entry(str(eid), diary_dir=_diary_dir(params), unarchive=unarchive)
    return _ok(entry=e.to_dict())


def cmd_entry_delete(params: dict) -> dict:
    from .history import delete_entry

    eid = params.get("entry_id") or params.get("id")
    if not eid:
        return _err("entry_id required")
    result = delete_entry(
        str(eid),
        diary_dir=_diary_dir(params),
        delete_audio=bool(params.get("delete_audio")),
    )
    return _ok(**result)


def cmd_record(params: dict) -> dict:
    """Record mic audio (fixed duration); returns wav_path."""
    from diary_app.services.session import get_session_service
    from diary_app.core.logutil import CancelledError

    try:
        wav = get_session_service().record(
            duration=float(params.get("duration") or 30),
            diary_dir=_diary_dir(params),
            silence_stop=bool(params.get("silence_stop")),
            device_id=params.get("device_id"),
        )
        return _ok(wav_path=str(wav), duration=float(params.get("duration") or 30))
    except CancelledError as e:
        return _err(str(e), cancelled=True)
    except Exception as e:
        return _err(f"Recording failed: {e}")


def cmd_record_start(params: dict) -> dict:
    """Start interactive recording session (hotkey Start)."""
    from diary_app.core.audio import interactive_start

    try:
        st = interactive_start(
            device=params.get("device_id"),
            max_duration=float(params.get("max_duration") or 3600),
        )
        return _ok(**st)
    except Exception as e:
        return _err(str(e))


def cmd_record_pause(params: dict) -> dict:
    from diary_app.core.audio import interactive_pause

    try:
        return _ok(**interactive_pause())
    except Exception as e:
        return _err(str(e))


def cmd_record_resume(params: dict) -> dict:
    from diary_app.core.audio import interactive_resume

    try:
        return _ok(**interactive_resume())
    except Exception as e:
        return _err(str(e))


def cmd_record_stop(params: dict) -> dict:
    """Stop interactive recording and write WAV."""
    from diary_app.core.audio import interactive_stop

    try:
        st = interactive_stop(diary_dir=_diary_dir(params))
        if st.get("error") and not st.get("wav_path"):
            return _err(st["error"], **{k: v for k, v in st.items() if k != "error"})
        return _ok(**st)
    except Exception as e:
        return _err(str(e))


def cmd_record_cancel(params: dict) -> dict:
    from diary_app.core.audio import interactive_cancel

    try:
        return _ok(**interactive_cancel())
    except Exception as e:
        return _err(str(e))


def cmd_record_status(params: dict) -> dict:
    from diary_app.core.audio import interactive_status

    return _ok(**interactive_status())


def cmd_transcribe(params: dict) -> dict:
    """Transcribe a file via SessionService (same path as CLI / Gradio)."""
    from diary_app.services.session import get_session_service
    from diary_app.core.logutil import CancelledError

    audio_path = params.get("audio_path") or params.get("file")
    if not audio_path:
        return _err("audio_path required")
    try:
        svc = get_session_service()
        result = svc.run(
            audio_path=audio_path,
            backend=params.get("backend"),
            device=params.get("device"),
            diary_dir=_diary_dir(params),
            analyze=params.get("analyze", True) is not False,
            persist=params.get("persist", True) is not False,
            sync_action_inbox=params.get("sync_actions", True) is not False,
            max_speakers=params.get("max_speakers"),
            model_size=params.get("model_size"),
            use_cache=bool(params.get("use_cache")),
        )
        return result.to_api_dict()
    except CancelledError as e:
        return _err(str(e), cancelled=True)
    except Exception as e:
        return _err(str(e))


def cmd_rebuild_index(params: dict) -> dict:
    from .index_db import rebuild_index

    n = rebuild_index(_diary_dir(params))
    return _ok(count=n)


def cmd_crypto_status(params: dict) -> dict:
    from .crypto import encryption_enabled, generate_key, ensure_key_file

    action = params.get("action") or "status"
    if action == "generate_key":
        return _ok(key=generate_key())
    if action == "ensure_key_file":
        path = ensure_key_file()
        return _ok(path=str(path))
    return _ok(enabled=encryption_enabled())


COMMANDS: dict[str, Callable[[dict], dict]] = {
    "history_list": cmd_history_list,
    "history_get": cmd_history_get,
    "search": cmd_search,
    "speakers_rename": cmd_speakers_rename,
    "speakers_roster": cmd_speakers_roster,
    "export": cmd_export,
    "digest": cmd_digest,
    "actions_inbox": cmd_actions_inbox,
    "actions_done": cmd_actions_done,
    "entry_annotate": cmd_entry_annotate,
    "entry_archive": cmd_entry_archive,
    "entry_delete": cmd_entry_delete,
    "record": cmd_record,
    "record_start": cmd_record_start,
    "record_pause": cmd_record_pause,
    "record_resume": cmd_record_resume,
    "record_stop": cmd_record_stop,
    "record_cancel": cmd_record_cancel,
    "record_status": cmd_record_status,
    "transcribe": cmd_transcribe,
    "rebuild_index": cmd_rebuild_index,
    "crypto_status": cmd_crypto_status,
}


def dispatch(command: str, params: dict | None = None) -> dict:
    ensure_logging()
    params = params or {}
    fn = COMMANDS.get(command)
    if not fn:
        return _err(f"Unknown command: {command}", commands=sorted(COMMANDS))
    try:
        return fn(params)
    except Exception as e:
        log.exception("api %s failed", command)
        return _err(str(e))


def run_api_argv(argv: list[str] | None = None) -> int:
    """CLI entry for `python -m diary_app api ...`."""
    ensure_logging()
    parser = argparse.ArgumentParser(prog="diary_app api", description="JSON IPC for diary_app")
    parser.add_argument("command", nargs="?", help="API command name")
    parser.add_argument(
        "--json",
        "-j",
        default=None,
        help="JSON object of parameters (merged with --set flags)",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set a string parameter (repeatable)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read full request JSON from stdin: {command, ...params}",
    )
    args = parser.parse_args(argv)

    params: dict[str, Any] = {}
    command = args.command

    if args.stdin or (not command and not sys.stdin.isatty()):
        raw = sys.stdin.read()
        if raw.strip():
            try:
                body = json.loads(raw)
            except json.JSONDecodeError as e:
                print(json.dumps(_err(f"Invalid JSON on stdin: {e}")), flush=True)
                return 1
            if isinstance(body, dict):
                command = body.pop("command", None) or body.pop("cmd", None) or command
                params.update(body)

    if args.json:
        try:
            extra = json.loads(args.json)
            if isinstance(extra, dict):
                params.update(extra)
        except json.JSONDecodeError as e:
            print(json.dumps(_err(f"Invalid --json: {e}")), flush=True)
            return 1

    for item in args.set:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        params[k] = v

    if not command:
        print(
            json.dumps(
                _err("command required", commands=sorted(COMMANDS)),
                indent=2,
            ),
            flush=True,
        )
        return 1

    result = dispatch(str(command), params)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1
