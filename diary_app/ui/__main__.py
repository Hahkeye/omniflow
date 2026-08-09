"""Entry point for `python -m diary_app.ui` / `python -m diary_app.ui.app`."""
import os

from .app import create_ui

if __name__ == "__main__":
    # Default to localhost only (private diary data). Set DIARY_UI_HOST=0.0.0.0 to bind all.
    host = os.environ.get("DIARY_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("DIARY_UI_PORT", "7860"))
    create_ui().launch(server_name=host, server_port=port, share=False)
