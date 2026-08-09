"""Diary Transcript CLI entry — argparse + dispatch only.

Command implementations live under diary_app.cli.* and call SessionService.
"""
from __future__ import annotations

import sys
from pathlib import Path

from diary_app.config import load_config
from diary_app.core.logutil import ensure_logging
from diary_app.cli.commands import get_command_handlers
from diary_app.cli.parser import build_parser


def main() -> None:
    """Main entry point."""
    ensure_logging()
    cfg = load_config()
    # Keep CLI path defaults in sync with AppConfig
    import diary_app.cli.common as cli_common

    cli_common.DIARY_DIR = Path(cfg.diary_dir)
    cfg.ensure_dirs()

    # Fast path for API / serve (used by Tauri & desktop shell)
    if len(sys.argv) >= 2 and sys.argv[1] == "api":
        from diary_app.core.api import run_api_argv

        sys.exit(run_api_argv(sys.argv[2:]))
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        from diary_app.core.daemon import run_serve_argv

        sys.exit(run_serve_argv(sys.argv[2:]))

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "speakers" and not getattr(args, "action", None):
        args.action = "list"
    if args.command == "actions" and not getattr(args, "action", None):
        args.action = "list"

    handlers = get_command_handlers()
    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
