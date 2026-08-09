"""CLI command registry — thin re-exports for main/parser compatibility.

Implementations live in:
  session_cmds  — record / transcribe / analyze / diary
  history_cmds  — history / list / speakers / search / archive / delete / reindex
  tools_cmds    — actions / tag / export / digest / devices / doctor / config / daemon
  common        — shared console, paths, display helpers
  handlers      — SessionService adapters
"""
from __future__ import annotations

# Re-export symbols expected by main.py / parser.py / external callers
from diary_app.cli.common import (  # noqa: F401
    BACKEND_CHOICES,
    DIARY_DIR,
    add_backend_args,
    display_results,
    resolve_output_path,
    _add_backend_args,
)
from diary_app.cli.history_cmds import (  # noqa: F401
    do_history,
    do_list,
    do_search,
    do_speakers,
)
from diary_app.cli.session_cmds import (  # noqa: F401
    do_analyze,
    do_diary,
    do_record,
    do_transcribe,
)
from diary_app.cli.tools_cmds import (  # noqa: F401
    do_actions,
    do_api,
    do_archive,
    do_config,
    do_daemon,
    do_delete,
    do_devices,
    do_digest,
    do_doctor,
    do_export,
    do_reindex,
    do_serve,
    do_tag,
)


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
