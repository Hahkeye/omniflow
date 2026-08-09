"""CLI handlers that call application services (not backends directly)."""
from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from diary_app.config import get_config
from diary_app.services.pipeline import PipelineResult, record_audio, run_session

console = Console()


def run_record(args) -> Path:
    """CLI record → WAV path."""
    cfg = get_config()
    out = getattr(args, "output", None)
    diary = Path(out).expanduser() if out else Path(cfg.diary_dir)
    if out and Path(out).suffix.lower() in {".wav", ".json", ".txt"}:
        # file path: use parent as diary for now; save with explicit name via pipeline later
        diary = Path(out).expanduser().parent
    duration = getattr(args, "duration", None)
    silence = bool(getattr(args, "silence_stop", False))
    wav = record_audio(
        duration=float(duration) if duration else 30.0,
        diary_dir=diary,
        silence_stop=silence,
    )
    if out and Path(out).suffix.lower() == ".wav":
        # move/copy to requested path
        dest = Path(out).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wav.read_bytes())
        wav = dest
    console.print(f"[green]✓ Recorded to {wav}[/green]")
    return wav


def run_transcribe(args) -> PipelineResult:
    cfg = get_config()
    wav = Path(args.file).expanduser().resolve()
    if not wav.exists():
        console.print(f"[red]File not found: {wav}[/red]")
        sys.exit(1)
    console.print(Panel(f"📝 Transcribing: {wav}", style="bold cyan"))
    result = run_session(
        audio_path=wav,
        backend=getattr(args, "backend", None) or cfg.default_backend,
        device=getattr(args, "device", None) or cfg.default_device,
        diary_dir=Path(args.output).expanduser()
        if getattr(args, "output", None) and Path(args.output).is_dir()
        else cfg.diary_dir,
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
    # record then pipeline
    wav = run_record(args)
    args.file = str(wav)
    return run_transcribe(args)
