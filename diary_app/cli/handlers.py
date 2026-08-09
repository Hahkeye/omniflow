"""CLI → SessionService adapters (no direct backend imports)."""
from __future__ import annotations

import sys
from pathlib import Path

from rich.panel import Panel

from diary_app.cli.common import console
from diary_app.config import get_config
from diary_app.services.pipeline import PipelineResult
from diary_app.services.session import get_session_service


def _diary_from_output(out: str | None) -> Path:
    cfg = get_config()
    if not out:
        return Path(cfg.diary_dir)
    p = Path(out).expanduser()
    if p.suffix.lower() in {".wav", ".json", ".txt"}:
        return p.parent
    return p


def run_record(args) -> Path:
    """CLI record → WAV path (via SessionService / pipeline)."""
    svc = get_session_service()
    out = getattr(args, "output", None)
    diary = _diary_from_output(out)
    duration = getattr(args, "duration", None)
    silence = bool(getattr(args, "silence_stop", False))
    device_id = getattr(args, "device_id", None)

    wav = svc.record(
        duration=float(duration) if duration else 30.0,
        diary_dir=diary,
        silence_stop=silence,
        device_id=device_id,
    )
    if out and Path(out).suffix.lower() == ".wav":
        dest = Path(out).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wav.read_bytes())
        wav = dest
    console.print(f"[green]✓ Recorded to {wav}[/green]")
    return wav


def run_transcribe(args) -> PipelineResult:
    cfg = get_config()
    svc = get_session_service()
    wav = Path(args.file).expanduser().resolve()
    if not wav.exists():
        console.print(f"[red]File not found: {wav}[/red]")
        sys.exit(1)

    model_size = None
    if getattr(args, "mps", False) or getattr(args, "device", None) in ("mps", "cuda"):
        # Prefer larger whisper when user asked for GPU / --mps
        if (getattr(args, "backend", None) or "").lower() == "whisper":
            model_size = "medium"

    console.print(Panel(f"📝 Transcribing: {wav}", style="bold cyan"))
    result = svc.run(
        audio_path=wav,
        backend=getattr(args, "backend", None) or cfg.default_backend,
        device=getattr(args, "device", None) or cfg.default_device,
        diary_dir=_diary_from_output(getattr(args, "output", None)),
        model_size=model_size,
    )
    if not result.ok:
        console.print(f"[red]Transcription failed: {result.error}[/red]")
        sys.exit(1)
    console.print(f"[green]✓ History entry {result.entry_id}[/green]")
    if result.transcript_path:
        console.print(f"  transcript: {result.transcript_path}")
    if result.analysis_path:
        console.print(f"  analysis:   {result.analysis_path}")
    if result.audio_path:
        console.print(f"  audio:      {result.audio_path}")
    for w in result.warnings or []:
        console.print(f"[yellow]⚠ {w}[/yellow]")
    return result


def run_diary(args) -> PipelineResult:
    cfg = get_config()
    console.print(Panel("[bold cyan]📒 Diary Transcript[/bold cyan]", style="bold cyan"))
    if getattr(args, "file", None):
        return run_transcribe(args)

    # Interactive mic pick lives in session_cmds; here we just pipeline-record
    duration = getattr(args, "duration", None)
    silence = bool(getattr(args, "silence_stop", False))
    device_id = getattr(args, "device_id", None)
    svc = get_session_service()
    wav = svc.record(
        duration=float(duration) if duration else 30.0,
        diary_dir=_diary_from_output(getattr(args, "output", None)),
        silence_stop=silence,
        device_id=device_id,
    )
    args.file = str(wav)
    return run_transcribe(args)
