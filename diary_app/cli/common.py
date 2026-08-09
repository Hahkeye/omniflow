"""Shared CLI utilities (console, paths, display, argparse helpers)."""
from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from diary_app.domain.models import KeyPoints, Transcript

console = Console()

# Updated each process start from AppConfig in main()
DIARY_DIR = Path.home() / "diary"
BACKEND_CHOICES = ("auto", "moss", "whisper", "nemo")


def resolve_output_path(output: str | Path | None, default_name: str) -> Path:
    """Treat --output as a file if it has a suffix, else as a directory."""
    if output is None:
        path = DIARY_DIR / default_name
    else:
        path = Path(output).expanduser()
        if path.suffix.lower() not in {".json", ".txt", ".wav"}:
            path = path / default_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def progress_update(fraction: float, status: str) -> None:
    console.print(f"  {status} ({fraction:.0%})")


def display_results(
    args,
    transcript: Transcript,
    key_points: KeyPoints,
    wav_path: Path | None,
) -> None:
    """Display transcript and analysis results."""
    console.print(
        Panel(
            f"[bold]📊 Results[/bold]\n"
            f"  Speakers: {len(transcript.speakers)}\n"
            f"  Duration: {transcript.duration:.0f}s\n"
            f"  Segments: {len(transcript.segments)}\n"
            f"  Output:   {wav_path or 'N/A'}",
            style="bold green",
        )
    )

    if key_points.speaker_stats:
        console.print(
            Panel(
                "[bold]👤 Speaker Statistics[/bold]\n"
                + "\n".join(
                    f"  {speaker}: {stats['word_count']} words ({stats['percentage']}%), "
                    f"{stats['duration_s']}s, {stats['segments']} segments"
                    for speaker, stats in key_points.speaker_stats.items()
                ),
                style="cyan",
            )
        )

    if key_points.topics:
        console.print(
            Panel(
                "[bold]🏷 Topics[/bold]\n"
                + "\n".join(f"  • {topic}" for topic in key_points.topics),
                style="yellow",
            )
        )

    if key_points.key_points:
        console.print(
            Panel(
                "[bold]📌 Key Points[/bold]\n"
                + "\n".join(f"  {i + 1}. {kp}" for i, kp in enumerate(key_points.key_points)),
                style="blue",
            )
        )

    if getattr(key_points, "decisions", None):
        console.print(
            Panel(
                "[bold]✓ Decisions[/bold]\n"
                + "\n".join(f"  • {d}" for d in key_points.decisions),
                style="magenta",
            )
        )

    if getattr(key_points, "action_items", None):
        console.print(
            Panel(
                "[bold]☐ Action items[/bold]\n"
                + "\n".join(f"  • {a}" for a in key_points.action_items),
                style="bright_yellow",
            )
        )

    if key_points.takeaways:
        console.print(
            Panel(
                "[bold]✅ Takeaways[/bold]\n"
                + "\n".join(f"  {ta}" for ta in key_points.takeaways),
                style="green",
            )
        )

    if args and getattr(args, "show_transcript", False):
        console.print(
            Panel(
                "[bold]📄 Full Transcript[/bold]\n\n" + transcript.format(),
                style="white",
            )
        )


def add_backend_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        choices=list(BACKEND_CHOICES),
        default="auto",
        help="Backend: moss (default Mac+PC model), whisper, nemo, or auto",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Compute device: auto (CUDA→MPS→CPU), cuda, cuda:0, mps, or cpu",
    )
    parser.add_argument(
        "--mps",
        action="store_true",
        help="Prefer larger whisper model when using whisper backend",
    )
    parser.add_argument(
        "--show-transcript",
        action="store_true",
        help="Show full transcript in results",
    )


# Back-compat alias used by parser
_add_backend_args = add_backend_args
