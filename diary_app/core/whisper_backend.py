"""Mac/CPU fallback backend using whisperx ASR.

For Apple Silicon Macs, whisper-medium/large-v3 runs on MPS.
For Linux/CPU, whisper-small runs reasonably fast.
"""

import gc
import numpy as np
from pathlib import Path

try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import whisperx
    HAS_WHISPERX = True
except ImportError:
    HAS_WHISPERX = False

from .transcribe import BaseTranscriptionBackend, Transcript, SpeakerSegment

# Models: medium (Mac/M1+), small (CPU fallback)
WHISPER_MEDIUM = "medium"
WHISPER_SMALL = "small"

def _load_audio(file: str) -> np.ndarray:
    """Load audio file, preferring whisperx/ffmpeg, falling back to torchaudio."""
    import subprocess
    # Try whisperx first (uses ffmpeg)
    try:
        return whisperx.load_audio(file)
    except (RuntimeError, FileNotFoundError):
        pass
    # Fall back to torchaudio for WAV files (no ffmpeg needed)
    try:
        import torchaudio
        wav, sr = torchaudio.load(file)
        if wav.shape[0] > 1:
            wav = wav.mean(0)
        return wav.numpy().flatten()
    except Exception as e:
        raise RuntimeError(f"Failed to load audio {file}: {e}")
def _get_device():
    """Return the best available device."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"
class WhisperBackend(BaseTranscriptionBackend):
    """WhisperX ASR backend for Mac/CPU."""

    name = "whisper"
    description = "WhisperX ASR, CPU/Mac/Windows"

    def __init__(self, model_size: str = WHISPER_MEDIUM, warmup: bool = True, max_speakers: int = 4):
        if not HAS_WHISPER:
            raise RuntimeError(
                "whisper not installed. Run:\n"
                "  pip install openai-whisper"
            )
        if not HAS_WHISPERX:
            raise RuntimeError(
                "whisperx not installed. Run:\n"
                "  pip install whisperx"
            )
        super().__init__(max_speakers)
        self.device = _get_device()
        self.model_size = model_size
        print(f"Whisper backend: model={model_size}, device={self.device}")
        if warmup:
            self.warmup()
    def warmup(self) -> None:
        """Download and warm up models."""
        from whisperx.asr import load_model as whisperx_load_model
        print(f"Loading whisperx model: {self.model_size} (device: {self.device})...")
        self.pipeline = whisperx_load_model(
            self.model_size, device=self.device,
            language="en",
        )
        # Load alignment model (whisperx 3.x API)
        from whisperx.alignment import load_align_model
        print(f"Loading alignment model...")
        align_model, align_metadata = load_align_model(
            language_code="en", device=self.device,
        )
        self.align_model = align_model
        self.align_metadata = align_metadata
        print("Models ready.")
    def transcribe(self, wav_path: Path) -> Transcript:
        """Transcribe audio with whisperx."""
        wav_path = Path(wav_path).resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")

        print(f"Transcribing: {wav_path}")
        audio = _load_audio(str(wav_path))

        # Transcribe with whisperx
        print("Running transcription...")
        result = self.pipeline.transcribe(
            audio, language="en", batch_size=8,
        )

        # Align timestamps (whisperx 3.x API)
        print("Aligning timestamps...")
        from whisperx.alignment import align
        aligned = align(
            result["segments"], self.align_model, self.align_metadata,
            audio, self.device, return_char_alignments=False,
        )

        # Build segments (no diarization)
        segments = self._build_segments(aligned["segments"])
        return Transcript(segments=segments)

    def _build_segments(self, aligned_segments) -> list[SpeakerSegment]:
        """Build SpeakerSegments from whisperx output."""
        segments = []
        default_speaker = self.get_speaker_ids()[0]

        for seg in aligned_segments:
            text = seg["text"].strip()
            if not text:
                continue

            segments.append(SpeakerSegment(
                speaker=default_speaker,
                start_time=seg["start"],
                end_time=seg["end"],
                text=text,
            ))

        segments.sort(key=lambda s: s.start_time)
        return segments
