"""Moss-Transcribe-Diarize backend for MOSS-Transcribe-Diarize 0.9B."""
import numpy as np
from pathlib import Path
from typing import Optional

from .transcribe import BaseTranscriptionBackend, Transcript, SpeakerSegment

_HAS_MOSS = False

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor
    from moss_transcribe_diarize import parse_transcript
    from moss_transcribe_diarize.inference_utils import (
        build_transcription_messages,
        generate_transcription,
        resolve_device,
    )
    _HAS_MOSS = True
except ImportError:
    _HAS_MOSS = False

# Models
MOSS_MODEL_ID = "OpenMOSS-Team/MOSS-Transcribe-Diarize"

# Model cache
_models = {"model": None, "processor": None}

class MossBackend(BaseTranscriptionBackend):
    """MOSS-Transcribe-Diarize backend for CPU/Mac/NVIDIA."""

    name = "moss"
    description = "MOSS-Transcribe-Diarize 0.9B (ASR + Diarization, CPU/GPU)"

    def __init__(self, warmup: bool = True, max_speakers: int = 4):
        if not _HAS_MOSS:
            raise RuntimeError(
                "moss-transcribe-diarize not installed. Run:\n"
                "  pip install moss-transcribe-diarize"
            )
        super().__init__(max_speakers)
        self.device = resolve_device("auto")
        print(f"Moss backend: model={MOSS_MODEL_ID}, device={self.device}")
        if warmup:
            self.warmup()

    def warmup(self) -> None:
        """Download and warm up models."""
        if _models["model"] is not None and _models["processor"] is not None:
            print("Models already loaded.")
            return

        dtype = torch.bfloat16 if self.device.type == "cuda" else torch.float32
        print(f"Loading MOSS model: {MOSS_MODEL_ID} (device: {self.device}, dtype: {dtype})...")

        _models["model"] = AutoModelForCausalLM.from_pretrained(
            MOSS_MODEL_ID,
            trust_remote_code=True,
            dtype="auto",
        ).to(dtype=dtype).to(self.device).eval()

        _models["processor"] = AutoProcessor.from_pretrained(
            MOSS_MODEL_ID,
            trust_remote_code=True,
        )

        print("Models ready.")

    def transcribe(self, wav_path: Path) -> Transcript:
        """Transcribe audio with MOSS-Transcribe-Diarize."""
        wav_path = Path(wav_path).resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")

        print(f"Transcribing: {wav_path}")
        messages = build_transcription_messages(str(wav_path))
        dtype = torch.bfloat16 if self.device.type == "cuda" else torch.float32

        print("Running transcription...")
        with torch.inference_mode():
            with torch.amp.autocast(self.device.type, enabled=True):
                with torch.no_grad():
                    result = generate_transcription(
                        _models["model"],
                        _models["processor"],
                        messages,
                        max_new_tokens=2048,
                        do_sample=False,
                        device=self.device,
                        dtype=dtype,
                    )

        # Parse the transcript
        print("Parsing transcript...")
        segments = self._parse_transcript(result["text"])
        return Transcript(segments=segments)

    def _parse_transcript(self, text: str) -> list[SpeakerSegment]:
        """Parse MOSS-Transcribe-Diarize output into SpeakerSegments."""
        try:
            parsed = list(parse_transcript(text))
        except Exception as e:
            print(f"Warning: Failed to parse transcript: {e}")
            # Fallback: try to parse manually
            return self._parse_transcript_fallback(text)

        segments = []
        for segment in parsed:
            text_content = segment.text.strip()
            if not text_content:
                continue

            # Map speaker labels
            speaker = segment.speaker

            segments.append(SpeakerSegment(
                speaker=speaker,
                start_time=float(segment.start),
                end_time=float(segment.end),
                text=text_content,
            ))

        segments.sort(key=lambda s: s.start_time)
        return segments

    def _parse_transcript_fallback(self, text: str) -> list[SpeakerSegment]:
        """Fallback parser for MOSS-Transcribe-Diarize output."""
        import re
        segments = []
        pattern = r'\[([0-9.]+)\]\[(S\d+)\]([^\[]+)?\[([0-9.]+)\]'
        for match in re.finditer(pattern, text):
            start, speaker, text_, end = match.groups()
            text_content = text_.strip() if text_ else ""
            if text_content:
                segments.append(SpeakerSegment(
                    speaker=speaker,
                    start_time=float(start),
                    end_time=float(end),
                    text=text_content,
                ))
        return segments
