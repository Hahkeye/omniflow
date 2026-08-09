"""Session commands: record / transcribe / analyze / diary."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.panel import Panel

from diary_app.cli import handlers as cli_handlers
from diary_app.cli.common import (
    DIARY_DIR,
    console,
    display_results,
    progress_update,
    resolve_output_path,
)
from diary_app.domain.models import KeyPoints, Transcript
from diary_app.services.session import get_session_service


def _pick_input_device() -> int | None:
    """Interactive mic selection when TTY has multiple inputs."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        input_devices = [
            (i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0
        ]
    except Exception:
        input_devices = []

    if not input_devices:
        console.print(
            Panel(
                "[red]No microphone input devices found![/red]\n\n"
                "If you're in WSL, audio capture isn't supported. Use "
                "[cyan]python -m diary_app transcribe <file>[/cyan] with a pre-recorded file.\n\n"
                "Or run on Mac/Linux/Windows with direct audio access.",
                style="bold red",
            )
        )
        sys.exit(1)

    if sys.stdin.isatty() and len(input_devices) > 1:
        for local_i, (dev_i, d) in enumerate(input_devices):
            console.print(f"  [{local_i}] {d['name']} (id={dev_i})")
        try:
            choice = int(input(f"Choose device [0-{len(input_devices) - 1}]: "))
        except (ValueError, EOFError):
            choice = 0
        choice = max(0, min(choice, len(input_devices) - 1))
        return input_devices[choice][0]
    return input_devices[0][0]


def do_record(args: argparse.Namespace) -> Path:
    """Record audio from the microphone via SessionService."""
    console.print(Panel("🎙 Recording", style="bold cyan"))
    device_id = _pick_input_device()
    args.device_id = device_id

    # Stream progress to the console while recording
    from diary_app.core.logutil import set_progress_sink, reset_progress_sink

    def _sink(payload: dict) -> None:
        frac = payload.get("fraction")
        if frac is None:
            frac = 0.0
        progress_update(float(frac), str(payload.get("message") or payload.get("phase") or ""))

    token = set_progress_sink(_sink)
    try:
        return cli_handlers.run_record(args)
    finally:
        reset_progress_sink(token)


def do_transcribe(args: argparse.Namespace) -> Transcript:
    """Transcribe an existing audio file (via session pipeline)."""
    result = cli_handlers.run_transcribe(args)
    transcript = Transcript.from_json(result.transcript or {})
    kp = KeyPoints.from_json(result.key_points or {})
    display_results(args, transcript, kp, Path(result.wav_path) if result.wav_path else None)
    return transcript


def do_analyze(args: argparse.Namespace) -> KeyPoints:
    """Analyze a transcript from a JSON file (via SessionService / registry analyzer)."""
    file_arg = getattr(args, "file", None)
    if not file_arg:
        candidates = sorted(
            DIARY_DIR.glob("transcript_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
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
    svc = get_session_service()
    try:
        transcript, key_points = svc.analyze_file(transcript_path)
    except Exception as e:
        console.print(f"[red]Analysis failed: {e}[/red]")
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = resolve_output_path(args.output, f"analysis_{ts}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({"key_points": key_points.to_json()}, f, indent=2)
    console.print(f"[green]✓ Key points saved to {save_path}[/green]")

    display_results(None, transcript, key_points, None)
    return key_points


def do_diary(args: argparse.Namespace) -> None:
    """Full diary workflow via session pipeline."""
    if not getattr(args, "file", None):
        console.print(Panel("🎙 Recording", style="bold cyan"))
        args.device_id = _pick_input_device()
    result = cli_handlers.run_diary(args)
    if not result.ok:
        console.print(f"[red]Diary session failed: {result.error}[/red]")
        sys.exit(1)
    transcript = Transcript.from_json(result.transcript or {})
    kp = KeyPoints.from_json(result.key_points or {})
    display_results(args, transcript, kp, Path(result.wav_path) if result.wav_path else None)
