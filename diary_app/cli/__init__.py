"""Thin CLI layer: parser + command handlers → SessionService / pipeline."""

from .handlers import run_diary, run_transcribe, run_record

__all__ = ["run_diary", "run_transcribe", "run_record"]
