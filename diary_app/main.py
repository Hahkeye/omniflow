"""Diary Transcript CLI — record audio, transcribe (multi-speaker), and analyze."""
import json
import argparse
import sys
import time
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from .core.audio import AudioConfig
from .core.transcribe import Transcript, KeyPoints
from .core.analyzer import TranscriptAnalyzer
from .core.nemo_backend import NeMoBackend
from .core.whisper_backend import WhisperBackend
from .core.moss_backend import MossBackend

console = Console()

def get_backend(args, max_speakers: int = 4) -> NeMoBackend | WhisperBackend | MossBackend:
    """Choose the appropriate transcription backend based on args."""
    if args.backend == "nemo":
        return NeMoBackend(max_speakers=max_speakers)
    elif args.backend == "whisper":
        model_size = "medium" if args.mps else "small"
        return WhisperBackend(model_size=model_size, max_speakers=max_speakers)
    elif args.backend == "moss":
        return MossBackend(max_speakers=max_speakers)
    else:
        # Auto-detect: try moss first, then whisper, then nemo
        try:
            return MossBackend(max_speakers=max_speakers)
        except Exception:
            console.print("[yellow]Moss not available, trying whisper...[/]")
            try:
                return WhisperBackend(max_speakers=max_speakers)
            except Exception as e:
                console.print(f"[yellow]Whisper not available ({e}), trying NeMo...[/]")
                try:
                    return NeMoBackend(max_speakers=max_speakers)
                except Exception as e2:
                    console.print(f"[red]NeMo not available ({e2}). No transcription backend available.[/]")
                    sys.exit(1)

def do_record(args: argparse.Namespace) -> Path:
    """Record audio from the microphone."""
    console.print(Panel("🎙 Recording", style="bold cyan"))

    # Check for audio devices
    import sounddevice as sd
    try:
        devices = sd.query_devices()
        input_devices = [d for d in devices if d["max_input_channels"] > 0]
    except Exception:
        input_devices = []

    if not input_devices:
        console.print(Panel(
            "[red]No microphone input devices found![/red]\n\n"
            "If you're in WSL, audio capture isn't supported. Use "
            "[cyan]diary transcribe &lt;file&gt;[/cyan] with a pre-recorded audio file instead.\n\n"
            "Or run the diary app on a Mac/Linux system with direct audio access.\n"
            "You can record audio using any recording app and then "
            "[cyan]diary transcribe &lt;file&gt;[/cyan] to process it.",
            style="bold red",
        ))
        sys.exit(1)

    # Show device list (only if interactive)
    if sys.stdin.isatty() and len(input_devices) > 1:
        for i, d in enumerate(input_devices):
            console.print(f"  [{i}] {d['name']}")
        idx = int(input(f"Choose device [0-{len(input_devices)-1}]: "))
    else:
        # Non-interactive: use the default device (index 0)
        idx = 0

    if args.duration:
        config = AudioConfig(max_duration=args.duration)
    elif args.silence_stop:
        config = AudioConfig(max_duration=600)
    else:
        config = AudioConfig(max_duration=300)

    config.device = idx

    output_dir = args.output or Path.home() / "diary"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    wav_path = output_dir / f"recording_{timestamp}.wav"

    if args.silence_stop:
        audio = config.record_until_silence(progress_callback=progress_update)
    else:
        audio = config.record(progress_callback=progress_update)

    if audio.size == 0:
        console.print("[red]No audio recorded![/red]")
        sys.exit(1)

    config.save_wav(audio, wav_path)
    console.print(f"[green]✓ Recorded to {wav_path}[/green]")
    return wav_path

def progress_update(
    fraction: float, status: str
):
    """Callback for recording progress."""
    console.print(f"  {status} ({fraction:.0%})")

def do_transcribe(args: argparse.Namespace) -> Transcript:
    """Transcribe an existing audio file."""
    wav_path = Path(args.file).resolve()
    if not wav_path.exists():
        console.print(f"[red]File not found: {wav_path}[/red]")
        sys.exit(1)

    console.print(Panel(f"📝 Transcribing: {wav_path}", style="bold cyan"))
    backend = get_backend(args)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Transcribing...", total=1.0)
        try:
            transcript = backend.transcribe(wav_path)
            progress.update(task, advance=1.0)
        except Exception as e:
            console.print(f"[red]Transcription failed: {e}[/red]")
            sys.exit(1)

    # Save transcript to JSON
    save_path = args.output or Path.home() / "diary" / f"transcript_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w") as f:
        json.dump({"transcript": transcript.to_json()}, f, indent=2)
    console.print(f"[green]✓ Transcript saved to {save_path}[/green]")

    # Analyze
    analyzer = TranscriptAnalyzer()
    key_points = analyzer.analyze(transcript)

    display_results(args, transcript, key_points, wav_path)

    return transcript

def do_analyze(args: argparse.Namespace) -> KeyPoints:
    """Analyze a transcript from a JSON file."""
    transcript_path = Path(args.file)
    if not transcript_path.exists():
        console.print(f"[red]Transcript file not found: {transcript_path}[/red]")
        sys.exit(1)

    console.print(Panel(f"🔍 Analyzing: {transcript_path}", style="bold cyan"))
    with open(transcript_path) as f:
        data = json.load(f)

    transcript = Transcript.from_json(data["transcript"])
    analyzer = TranscriptAnalyzer()
    key_points = analyzer.analyze(transcript)
    # Save key points to JSON
    save_path = args.output or Path.home() / "diary" / f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w") as f:
        json.dump({"key_points": key_points.to_json()}, f, indent=2)
    console.print(f"[green]✓ Key points saved to {save_path}[/green]")

    display_results(None, transcript, key_points, None)
    return key_points


def do_diary(args):
    """Run the full diary workflow: record → transcribe → analyze."""
    console.print(Panel("[bold cyan]📒 Diary Transcript[/bold cyan]", style="bold cyan"))

    if args.file:
        # File-based workflow: transcribe existing file → analyze
        console.print(Panel("📝 Transcribing from file", style="bold green"))
        wav_path = Path(args.file)
        if not wav_path.exists():
            console.print(f"[red]File not found: {wav_path}[/red]")
            sys.exit(1)
    else:
        # Recording workflow
        wav_path = do_record(args)

    # Transcribe
    backend = get_backend(args)
    transcript = backend.transcribe(wav_path)

    # Save transcript to JSON
    save_path = args.output or Path.home() / "diary" / f"transcript_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w") as f:
        json.dump({"transcript": transcript.to_json()}, f, indent=2)
    console.print(f"[green]✓ Transcript saved to {save_path}[/green]")

    # Analyze
    analyzer = TranscriptAnalyzer()
    key_points = analyzer.analyze(transcript)

    # Display results
    display_results(args, transcript, key_points, wav_path)

def display_results(args, transcript: Transcript, key_points: KeyPoints, wav_path: Path | None):
    """Display transcript and analysis results."""
    console.print(Panel(
        f"[bold]📊 Results[/bold]\n"
        f"  Speakers: {len(transcript.speakers)}\n"
        f"  Duration: {transcript.duration:.0f}s\n"
        f"  Segments: {len(transcript.segments)}\n"
        f"  Output:   {wav_path or 'N/A'}",
        style="bold green",
    ))

    # Speaker statistics
    if key_points.speaker_stats:
        console.print(Panel(
            "[bold]👤 Speaker Statistics[/bold]\n" + "\n".join(
                f"  {speaker}: {stats['word_count']} words ({stats['percentage']}%), "
                f"{stats['duration_s']}s, {stats['segments']} segments"
                for speaker, stats in key_points.speaker_stats.items()
            ),
            style="cyan",
        ))

    # Topics
    if key_points.topics:
        console.print(Panel(
            "[bold]🏷 Topics[/bold]\n" + "\n".join(
                f"  • {topic}" for topic in key_points.topics
            ),
            style="yellow",
        ))

    # Key points
    if key_points.key_points:
        console.print(Panel(
            "[bold]📌 Key Points[/bold]\n" + "\n".join(
                f"  {i+1}. {kp}" for i, kp in enumerate(key_points.key_points)
            ),
            style="blue",
        ))

    # Takeaways
    if key_points.takeaways:
        console.print(Panel(
            "[bold]✅ Takeaways[/bold]\n" + "\n".join(
                f"  {ta}" for ta in key_points.takeaways
            ),
            style="green",
        ))

    # Full transcript (optional)
    if args and getattr(args, "show_transcript", False):
        console.print(Panel(
            "[bold]📄 Full Transcript[/bold]\n\n" + transcript.format(),
            style="white",
        ))
def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Diary Transcript — record, transcribe multi-speaker audio, and analyze",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  diary diary                # Record + transcribe + analyze (auto backend)
  diary record               # Just record audio
  diary transcribe file.wav  # Transcribe existing file
  diary analyze              # Analyze latest recording
  diary diary --backend whisper  # Use whisper backend
  diary diary --mps --show-transcript  # Use whisper medium + show transcript
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    # diary (full workflow)
    diary = subparsers.add_parser("diary", help="Record + transcribe + analyze")
    diary.add_argument("--backend", choices=["nemo", "whisper", "moss"], default="auto",
                       help="Backend: nemo (GPU), whisper (CPU/Mac), or moss (ASR + diarization)")
    diary.add_argument("--mps", action="store_true", help="Use whisper-medium for better quality (Apple Silicon)")
    diary.add_argument("--duration", type=int, default=None,
                       help="Recording duration in seconds")
    diary.add_argument("--silence-stop", action="store_true",
                       help="Stop recording after silence period")
    diary.add_argument("--output", type=str, default=None,
                       help="Output directory for recordings")
    diary.add_argument("--show-transcript", action="store_true",
                       help="Show full transcript in results")
    diary.add_argument("--file", type=str, default=None,
                       help="Audio file to transcribe (skip recording)")

    # record
    record = subparsers.add_parser("record", help="Record audio from microphone")
    record.add_argument("--duration", type=int, default=None,
                        help="Recording duration in seconds")
    record.add_argument("--silence-stop", action="store_true",
                        help="Stop recording after silence period")
    record.add_argument("--output", type=str, default=None,
                        help="Output directory for recordings")

    # transcribe
    transcribe = subparsers.add_parser("transcribe", help="Transcribe an existing audio file")
    transcribe.add_argument("file", help="Audio file to transcribe (wav, mp3, etc.)")
    transcribe.add_argument("--backend", choices=["nemo", "whisper", "moss"], default="auto")
    transcribe.add_argument("--mps", action="store_true")
    transcribe.add_argument("--show-transcript", action="store_true")
    transcribe.add_argument("--output", type=str, default=None,
                            help="Output directory for transcription JSON")

    # analyze
    analyze = subparsers.add_parser("analyze", help="Analyze a transcript")
    analyze.add_argument("--file", help="Transcript JSON file to analyze")
    analyze.add_argument("--output", type=str, default=None,
                         help="Output directory for analysis JSON")

    # list
    subparsers.add_parser("list", help="List recent recordings")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Map command
    commands = {
        "diary": do_diary,
        "record": do_record,
        "transcribe": do_transcribe,
        "analyze": do_analyze,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    elif args.command == "list":
        # List recent recordings
        output_dir = args.output or Path.home() / "diary"
        files = sorted(Path(output_dir).glob("recording_*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
        if files:
            for f in files:
                size = f.stat().st_size / 1024 / 1024
                console.print(f"  {f.name} ({size:.1f} MB)")
        else:
            console.print("[yellow]No recordings found.[/yellow]")

if __name__ == "__main__":
    main()
