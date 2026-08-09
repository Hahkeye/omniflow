"""Whisper-based ASR backend (optional Mac/CPU/GPU fallback).

Provides transcription without full multi-speaker diarization by default.
If pyannote.audio is installed and HF_TOKEN is set, speaker diarization
is applied on top of whisperX alignment.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .transcribe import BaseTranscriptionBackend, Transcript, SpeakerSegment

try:
    import whisper  # noqa: F401
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import whisperx
    HAS_WHISPERX = True
except ImportError:
    HAS_WHISPERX = False

try:
    from pyannote.audio import Pipeline as PyannotePipeline
    HAS_PYANNOTE = True
except ImportError:
    HAS_PYANNOTE = False
    PyannotePipeline = None  # type: ignore

WHISPER_MEDIUM = "medium"
WHISPER_SMALL = "small"

_models: dict = {"pipeline": None, "align_model": None, "align_metadata": None, "diarize": None}


def _load_audio(file: str) -> np.ndarray:
    """Load audio file, preferring whisperx/ffmpeg, falling back to torchaudio/wave."""
    if HAS_WHISPERX:
        try:
            return whisperx.load_audio(file)
        except (RuntimeError, FileNotFoundError, OSError):
            pass

    try:
        import torchaudio
        wav, sr = torchaudio.load(file)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        return wav.squeeze(0).numpy().flatten()
    except Exception:
        pass

    # Last resort: stdlib wave for 16-bit PCM WAV
    import wave
    with wave.open(file, "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if wf.getnchannels() > 1:
            audio = audio.reshape(-1, wf.getnchannels()).mean(axis=1)
        if sr != 16000:
            # naive resample
            duration = len(audio) / sr
            target = int(duration * 16000)
            x_old = np.linspace(0, 1, num=len(audio), endpoint=False)
            x_new = np.linspace(0, 1, num=target, endpoint=False)
            audio = np.interp(x_new, x_old, audio).astype(np.float32)
        return audio


def _get_device(preferred: str = "auto") -> str:
    """Return the best available device string for whisperx (cuda/cpu).

    WhisperX is most reliable on CUDA or CPU; MPS often falls back to CPU.
    """
    from .device import resolve_torch_device, cuda_available

    preferred = (preferred or "auto").strip().lower()
    if preferred in ("cuda", "cpu") or preferred.startswith("cuda:"):
        info = resolve_torch_device(preferred)
        return "cuda" if info.kind == "cuda" else "cpu"
    if preferred == "mps":
        # whisperx: prefer CPU over flaky MPS
        return "cpu"
    # auto
    if cuda_available():
        return "cuda"
    return "cpu"


class WhisperBackend(BaseTranscriptionBackend):
    """WhisperX ASR backend (optional). Diarization requires pyannote + HF token."""

    name = "whisper"
    description = "WhisperX ASR (optional diarization via pyannote)"

    def __init__(
        self,
        model_size: str = WHISPER_MEDIUM,
        warmup: bool = True,
        max_speakers: int = 4,
        enable_diarization: bool = True,
        device: str = "auto",
    ):
        if not HAS_WHISPER and not HAS_WHISPERX:
            raise RuntimeError(
                "whisper/whisperx not installed. Optional install:\n"
                "  pip install -r diary_app/requirements-whisper.txt"
            )
        if not HAS_WHISPERX:
            raise RuntimeError(
                "whisperx not installed. Optional install:\n"
                "  pip install -r diary_app/requirements-whisper.txt"
            )
        super().__init__(max_speakers)
        self.device = _get_device(device)
        self.model_size = model_size
        self.enable_diarization = enable_diarization and HAS_PYANNOTE
        print(
            f"Whisper backend: model={model_size}, device={self.device}, "
            f"diarization={'on' if self.enable_diarization else 'off'}"
        )
        if warmup:
            self.warmup()

    def warmup(self) -> None:
        """Download and warm up models."""
        from whisperx.asr import load_model as whisperx_load_model
        from whisperx.alignment import load_align_model

        print(f"Loading whisperx model: {self.model_size} (device: {self.device})...")
        self.pipeline = whisperx_load_model(
            self.model_size,
            device=self.device,
            language="en",
        )
        print("Loading alignment model...")
        align_model, align_metadata = load_align_model(
            language_code="en",
            device=self.device,
        )
        self.align_model = align_model
        self.align_metadata = align_metadata

        self.diarize_pipeline = None
        if self.enable_diarization:
            token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
            if not token:
                print(
                    "pyannote diarization skipped: set HF_TOKEN to enable "
                    "(accept model terms on Hugging Face first)."
                )
            else:
                try:
                    print("Loading pyannote diarization pipeline...")
                    self.diarize_pipeline = PyannotePipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        use_auth_token=token,
                    )
                    import torch
                    self.diarize_pipeline.to(torch.device(self.device if self.device != "mps" else "cpu"))
                except Exception as e:
                    print(f"pyannote diarization unavailable: {e}")
                    self.diarize_pipeline = None

        print("Models ready.")

    def unload(self) -> None:
        self.pipeline = None
        self.align_model = None
        self.align_metadata = None
        self.diarize_pipeline = None
        import gc
        gc.collect()

    def transcribe(self, wav_path: Path) -> Transcript:
        """Transcribe audio with whisperx (+ optional pyannote diarization)."""
        wav_path = Path(wav_path).resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")

        print(f"Transcribing: {wav_path}")
        audio = _load_audio(str(wav_path))

        print("Running transcription...")
        result = self.pipeline.transcribe(audio, language="en", batch_size=8)

        print("Aligning timestamps...")
        from whisperx.alignment import align
        aligned = align(
            result["segments"],
            self.align_model,
            self.align_metadata,
            audio,
            self.device,
            return_char_alignments=False,
        )

        segments_raw = aligned["segments"]

        if self.diarize_pipeline is not None:
            print("Running speaker diarization...")
            try:
                diarize_segments = self.diarize_pipeline(str(wav_path))
                # Prefer whisperx.assign_word_speakers when available
                try:
                    from whisperx.diarize import assign_word_speakers
                    labeled = assign_word_speakers(diarize_segments, aligned)
                    segments_raw = labeled["segments"]
                except Exception:
                    segments_raw = self._assign_speakers_simple(segments_raw, diarize_segments)
            except Exception as e:
                print(f"Diarization failed, using single speaker: {e}")

        segments = self._build_segments(segments_raw)
        return Transcript(segments=segments)

    def _assign_speakers_simple(self, segments, diarize_result) -> list:
        """Fallback: map segment midpoints to diarization labels."""
        turns = []
        try:
            for turn, _, speaker in diarize_result.itertracks(yield_label=True):
                turns.append((turn.start, turn.end, speaker))
        except Exception:
            return segments

        out = []
        for seg in segments:
            mid = (float(seg["start"]) + float(seg["end"])) / 2.0
            label = None
            for start, end, speaker in turns:
                if start <= mid <= end:
                    label = speaker
                    break
            new_seg = dict(seg)
            if label:
                new_seg["speaker"] = label
            out.append(new_seg)
        return out

    def _build_segments(self, aligned_segments) -> list[SpeakerSegment]:
        """Build SpeakerSegments from whisperx output."""
        segments: list[SpeakerSegment] = []
        default_speaker = self.get_speaker_ids()[0]
        speaker_map: dict[str, str] = {}
        next_idx = 1

        for seg in aligned_segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue

            raw = seg.get("speaker")
            if raw is None:
                speaker = default_speaker
            else:
                key = str(raw)
                if key not in speaker_map:
                    speaker_map[key] = f"{self.speaker_prefix} {next_idx}"
                    next_idx += 1
                speaker = speaker_map[key]

            segments.append(
                SpeakerSegment(
                    speaker=speaker,
                    start_time=float(seg["start"]),
                    end_time=float(seg["end"]),
                    text=text,
                )
            )

        segments.sort(key=lambda s: s.start_time)
        return segments
