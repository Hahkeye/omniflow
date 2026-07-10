"""Gradio UI for the Diary Transcript app."""
import os
import json
import time
from pathlib import Path
from datetime import datetime

import gradio as gr
import numpy as np
import scipy.io.wavfile as wavfile

from ..core.audio import AudioConfig, record_microphone
from ..core.transcribe import Transcript
from ..core.whisper_backend import WhisperBackend
from ..core.nemo_backend import NeMoBackend
from ..core.analyzer import TranscriptAnalyzer

DIARY_DIR = Path.home() / "diary"
DIARY_DIR.mkdir(parents=True, exist_ok=True)

# Global backend instance (lazy-loaded)
_backend: NeMoBackend | WhisperBackend | None = None
_backend_type: str = "whisper"
_backend_size: str = "medium"

def get_backend():
    """Get or create the transcription backend."""
    global _backend, _backend_type, _backend_size
    if _backend is None:
        try:
            if _backend_type == "nemo":
                _backend = NeMoBackend(
                    model_size=_backend_size,
                    warmup=True,
                    max_speakers=4,
                )
            else:
                _backend = WhisperBackend(
                    model_size=_backend_size,
                    warmup=True,
                    max_speakers=4,
                )
        except Exception as e:
            return None, str(e)
    return _backend, None

def format_transcript(transcript: Transcript) -> str:
    """Format transcript for display."""
    if not transcript.segments:
        return "No speech detected."

    lines = []
    for seg in transcript.segments:
        lines.append(
            f"[{seg.speaker}] ({seg.start_time:.1f}s - {seg.end_time:.1f}s): {seg.text}"
        )
    return "\n".join(lines)

def format_analysis(key_points) -> str:
    """Format analysis results for display."""
    if not key_points:
        return ""

    cp = key_points.get("key_points", {})
    lines = []

    if cp.get("summary"):
        lines.append(f"## Summary\n{cp['summary']}")
    if cp.get("key_points"):
        lines.append("## Key Points")
        for i, kp in enumerate(cp["key_points"], 1):
            lines.append(f"{i}. {kp}")
    if cp.get("topics"):
        lines.append("## Topics")
        for t in cp["topics"]:
            lines.append(f"• {t}")
    if cp.get("takeaways"):
        lines.append("## Takeaways")
        for ta in cp["takeaways"]:
            lines.append(f"• {ta}")

    return "\n\n".join(lines)

def record_button_action(duration: float, sr: int, max_speakers: int):
    """Record from microphone and save to WAV."""
    try:
        config = AudioConfig(
            sample_rate=sr,
            num_channels=1,
            duration=duration,
            max_speakers=max_speakers,
        )
        wav_path = record_microphone(config)
        if wav_path:
            return str(wav_path), "Recording saved successfully."
        return None, "Recording failed."
    except Exception as e:
        return None, f"Recording error: {e}"

def transcribe_button_action(wav_file, backend_type, backend_size, max_speakers):
    """Transcribe an audio file."""
    global _backend, _backend_type, _backend_size
    wav_path = Path(wav_file) if wav_file else None
    if not wav_path or not wav_path.exists():
        return "", "No audio file selected.", "", ""

    _backend_type = backend_type
    _backend_size = backend_size

    try:
        backend, err = get_backend()
        if not backend:
            return "", err, "", ""

        transcript = backend.transcribe(wav_path)
        if not transcript.segments:
            return "No speech detected in the audio.", "", "", ""

        # Transcribe
        lines = []
        for seg in transcript.segments:
            lines.append(
                f"[{seg.speaker}] ({seg.start_time:.1f}s - {seg.end_time:.1f}s): {seg.text}"
            )
        transcript_text = "\n".join(lines)

        # Analyze
        analyzer = TranscriptAnalyzer()
        analyzer.set_segments(transcript.segments)
        key_points = analyzer.analyze()
        analysis_text = format_analysis(key_points)

        # Save
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        transcript_path = DIARY_DIR / f"transcript_{ts}.json"
        analysis_path = DIARY_DIR / f"analysis_{ts}.json"

        # Save transcript JSON
        transcript_data = {
            "transcript": {
                "segments": [
                    {
                        "speaker": s.speaker,
                        "start": s.start_time,
                        "end": s.end_time,
                        "text": s.text,
                    }
                    for s in transcript.segments
                ]
            }
        }
        transcript_path.write_text(json.dumps(transcript_data, indent=2))

        # Save analysis JSON
        analysis_path.write_text(json.dumps(key_points, indent=2))

        return transcript_text, analysis_text, str(transcript_path), str(analysis_path)

    except Exception as e:
        return "", f"Transcription error: {e}", "", ""

def load_file_action(file_path, backend_type, backend_size, max_speakers):
    """Load and transcribe a file directly."""
    return transcribe_button_action(file_path, backend_type, backend_size, max_speakers)

def load_latest_action(backend_type, backend_size, max_speakers):
    """Load the latest recording and transcribe it."""
    recordings = sorted(
        DIARY_DIR.glob("recording_*.wav"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not recordings:
        return "", "No recordings found.", "", ""

    return transcribe_button_action(
        str(recordings[0]), backend_type, backend_size, max_speakers
    )

def create_ui():
    """Create the Gradio UI."""
    with gr.Blocks(title="Diary Transcript", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 🎙️ Diary Transcript")
        gr.Markdown("Record, transcribe, and analyze multi-speaker audio conversations.")

        # Settings section
        with gr.Accordion("Settings", open=False):
            with gr.Row():
                backend_type = gr.Radio(
                    ["whisper", "nemo"],
                    value="whisper",
                    label="Backend",
                    interactive=True,
                )
                backend_size = gr.Radio(
                    ["small", "medium"],
                    value="medium",
                    label="Model Size (Whisper)",
                    interactive=True,
                )
                max_speakers = gr.Slider(
                    1, 4, value=4, step=1, label="Max Speakers",
                    interactive=True,
                )
                sample_rate = gr.Radio(
                    [16000], value=16000, label="Sample Rate (Hz)",
                    interactive=False,  # Only one option for now
                )

        # File input section
        with gr.Tab("File"):
            file_input = gr.File(label="Upload Audio File", type="filepath")
            with gr.Row():
                btn_transcribe = gr.Button("Transcribe File", variant="primary")
                btn_load_latest = gr.Button("Load Latest Recording", variant="secondary")
            transcript_output = gr.Textbox(label="Transcript", lines=15, interactive=False)
            analysis_output = gr.Textbox(label="Analysis", lines=10, interactive=False)
            with gr.Row():
                transcript_path = gr.Textbox(label="Transcript Saved", lines=1, interactive=False)
                analysis_path = gr.Textbox(label="Analysis Saved", lines=1, interactive=False)

        # Recording section
        with gr.Tab("Record"):
            duration_input = gr.Slider(
                10, 300, value=60, step=5, label="Recording Duration (seconds)",
                interactive=True,
            )
            with gr.Row():
                btn_record = gr.Button("Start Recording", variant="primary")
                btn_stop = gr.Button("Stop", variant="stop")
            recording_output = gr.Textbox(label="Recording Status", lines=1, interactive=False)
            wav_file_output = gr.File(label="Recording", interactive=False)

        # Connect button actions
        btn_transcribe.click(
            fn=transcribe_button_action,
            inputs=[file_input, backend_type, backend_size, max_speakers],
            outputs=[transcript_output, analysis_output, transcript_path, analysis_path],
        )

        btn_load_latest.click(
            fn=load_latest_action,
            inputs=[backend_type, backend_size, max_speakers],
            outputs=[transcript_output, analysis_output, transcript_path, analysis_path],
        )

        btn_record.click(
            fn=record_button_action,
            inputs=[duration_input, sample_rate, max_speakers],
            outputs=[wav_file_output, recording_output],
        )

    return app

if __name__ == "__main__":
    ui = create_ui()
    ui.launch(server_name="0.0.0.0", server_port=7860, share=False)
