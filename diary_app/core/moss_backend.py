"""MOSS-Transcribe-Diarize backend (ASR + diarization, Mac + PC)."""
from __future__ import annotations

import math
from pathlib import Path

from .device import resolve_torch_device, detect_hardware
from .transcribe import BaseTranscriptionBackend, Transcript, SpeakerSegment

_HAS_MOSS = False
_IMPORT_ERROR: str | None = None

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor
    from moss_transcribe_diarize import parse_transcript
    from moss_transcribe_diarize.inference_utils import (
        build_transcription_messages,
        generate_transcription,
    )
    _HAS_MOSS = True
except ImportError as e:
    _HAS_MOSS = False
    _IMPORT_ERROR = str(e)

MOSS_MODEL_ID = "OpenMOSS-Team/MOSS-Transcribe-Diarize"

# Shared model cache (one process)
_models: dict = {"model": None, "processor": None, "device": None, "dtype": None}

# Tokens-per-second of audio is rough; raise for long multi-speaker content.
# Official serve docs use up to 65536 for long audio.
_MIN_NEW_TOKENS = 2048
_MAX_NEW_TOKENS = 65536
_TOKENS_PER_AUDIO_SECOND = 12


def _pick_device(preferred: str = "auto"):
    """Resolve cuda → mps → cpu via shared detector."""
    info = resolve_torch_device(preferred)
    return info.torch_device


def _pick_dtype(device) -> "torch.dtype":
    """bf16/float16 on CUDA when supported; float32 elsewhere (Mac MPS/CPU)."""
    from .device import pick_dtype
    return pick_dtype(device)


def _estimate_max_new_tokens(wav_path: Path) -> int:
    """Scale generation budget with approximate audio duration."""
    duration_s = None
    try:
        import wave
        with wave.open(str(wav_path), "rb") as wf:
            duration_s = wf.getnframes() / float(wf.getframerate() or 1)
    except Exception:
        try:
            import torchaudio
            info = torchaudio.info(str(wav_path))
            if info.num_frames and info.sample_rate:
                duration_s = info.num_frames / float(info.sample_rate)
        except Exception:
            duration_s = None

    if duration_s is None or duration_s <= 0:
        return _MIN_NEW_TOKENS

    estimated = int(math.ceil(duration_s * _TOKENS_PER_AUDIO_SECOND))
    return max(_MIN_NEW_TOKENS, min(_MAX_NEW_TOKENS, estimated))


class MossBackend(BaseTranscriptionBackend):
    """MOSS-Transcribe-Diarize 0.9B — same model on Mac (MPS/CPU) and PC (CUDA/CPU)."""

    name = "moss"
    description = "MOSS-Transcribe-Diarize 0.9B (ASR + diarization, Mac/PC)"

    def __init__(
        self,
        warmup: bool = True,
        max_speakers: int = 4,
        device: str = "auto",
    ):
        if not _HAS_MOSS:
            hint = _IMPORT_ERROR or "unknown import error"
            raise RuntimeError(
                "moss-transcribe-diarize is not installed or not importable.\n"
                f"  Import error: {hint}\n"
                "  Install with:\n"
                "    pip install -r diary_app/requirements.txt\n"
                "  or:\n"
                "    pip install 'moss-transcribe-diarize @ git+https://github.com/OpenMOSS/MOSS-Transcribe-Diarize.git'\n"
                "  Avoid editable installs under /tmp — they break after reboot."
            )
        super().__init__(max_speakers)
        self.device_info = resolve_torch_device(device)
        self.device = self.device_info.torch_device
        self.dtype = _pick_dtype(self.device)
        # Show detection summary so users see CUDA when it's used
        hw = detect_hardware()
        print(f"Moss backend: model={MOSS_MODEL_ID}")
        print(f"  {self.device_info.details}")
        if self.device_info.kind == "cpu" and not hw["cuda_available"]:
            if hw.get("note"):
                print(f"  note: {hw['note'].splitlines()[0]}")
            elif hw["gpus"]:
                print("  note: GPUs listed but CUDA not ready — check torch CUDA build.")
            else:
                print("  note: no CUDA GPU detected; running on CPU (slower).")
        if warmup:
            self.warmup()

    def warmup(self) -> None:
        """Download and warm up models."""
        if _models["model"] is not None and _models["processor"] is not None:
            # Reuse if same device/dtype
            if _models["device"] == self.device and _models["dtype"] == self.dtype:
                print("Models already loaded.")
                return
            self.unload()

        print(
            f"Loading MOSS model: {MOSS_MODEL_ID} "
            f"(device: {self.device}, dtype: {self.dtype})..."
        )

        model = AutoModelForCausalLM.from_pretrained(
            MOSS_MODEL_ID,
            trust_remote_code=True,
            dtype="auto",
        )
        model = model.to(dtype=self.dtype).to(self.device).eval()

        processor = AutoProcessor.from_pretrained(
            MOSS_MODEL_ID,
            trust_remote_code=True,
        )

        _models["model"] = model
        _models["processor"] = processor
        _models["device"] = self.device
        _models["dtype"] = self.dtype
        print("Models ready.")

    def unload(self) -> None:
        """Release model weights (helps long sessions on Mac)."""
        _models["model"] = None
        _models["processor"] = None
        _models["device"] = None
        _models["dtype"] = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
            try:
                torch.mps.empty_cache()
            except Exception:
                pass
        import gc
        gc.collect()
        print("MOSS models unloaded.")

    def transcribe(self, wav_path: Path) -> Transcript:
        """Transcribe audio with MOSS-Transcribe-Diarize."""
        wav_path = Path(wav_path).resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")

        if _models["model"] is None or _models["processor"] is None:
            self.warmup()

        print(f"Transcribing: {wav_path}")
        messages = build_transcription_messages(str(wav_path))
        max_new_tokens = _estimate_max_new_tokens(wav_path)
        print(f"Running transcription (max_new_tokens={max_new_tokens})...")

        use_autocast = self.device.type == "cuda"
        try:
            with torch.inference_mode():
                if use_autocast:
                    with torch.amp.autocast(device_type="cuda", dtype=self.dtype):
                        result = generate_transcription(
                            _models["model"],
                            _models["processor"],
                            messages,
                            max_new_tokens=max_new_tokens,
                            do_sample=False,
                            device=self.device,
                            dtype=self.dtype,
                        )
                else:
                    result = generate_transcription(
                        _models["model"],
                        _models["processor"],
                        messages,
                        max_new_tokens=max_new_tokens,
                        do_sample=False,
                        device=self.device,
                        dtype=self.dtype,
                    )
        except Exception as e:
            # MPS can fail on some ops — fall back to CPU once
            if self.device.type == "mps":
                print(f"MPS inference failed ({e}); falling back to CPU...")
                self.device = torch.device("cpu")
                self.dtype = torch.float32
                self.warmup()
                with torch.inference_mode():
                    result = generate_transcription(
                        _models["model"],
                        _models["processor"],
                        messages,
                        max_new_tokens=max_new_tokens,
                        do_sample=False,
                        device=self.device,
                        dtype=self.dtype,
                    )
            else:
                raise

        raw_text = (result.get("text") or "").strip()
        print("Parsing transcript...")
        segments = self._parse_transcript(raw_text)
        warnings: list[str] = []
        if not segments:
            if raw_text:
                warnings.append(
                    "Model returned text that did not parse into timed speaker segments; "
                    "raw output is preserved."
                )
                print(f"Warning: no parseable segments. Raw model output: {raw_text[:200]!r}")
                # Single untimed segment so history/search still capture content
                if raw_text not in ("", "[Music]", "[Silence]", "[noise]"):
                    segments = [
                        SpeakerSegment(
                            speaker=f"{self.speaker_prefix} 1",
                            start_time=0.0,
                            end_time=0.0,
                            text=raw_text,
                        )
                    ]
                else:
                    warnings.append(
                        f"Non-speech or empty-sounding output: {raw_text!r}"
                    )
            else:
                warnings.append("Model returned empty text.")
                print("Warning: model returned empty transcription text.")
        for w in warnings:
            print(f"  ⚠ {w}")
        return Transcript(segments=segments, raw_text=raw_text, warnings=warnings)

    def _parse_transcript(self, text: str) -> list[SpeakerSegment]:
        """Parse MOSS-Transcribe-Diarize output into SpeakerSegments."""
        try:
            parsed = list(parse_transcript(text))
        except Exception as e:
            print(f"Warning: Failed to parse transcript: {e}")
            return self._parse_transcript_fallback(text)

        segments: list[SpeakerSegment] = []
        for segment in parsed:
            text_content = (segment.text or "").strip()
            if not text_content:
                continue
            speaker = self.map_speaker_label(segment.speaker)
            segments.append(
                SpeakerSegment(
                    speaker=speaker,
                    start_time=float(segment.start),
                    end_time=float(segment.end),
                    text=text_content,
                )
            )

        segments.sort(key=lambda s: s.start_time)
        return segments

    def _parse_transcript_fallback(self, text: str) -> list[SpeakerSegment]:
        """Fallback parser for MOSS [start][Sxx]text[end] output."""
        import re

        segments: list[SpeakerSegment] = []
        pattern = r"\[([0-9.]+)\]\[(S\d+)\]([^\[]*?)\[([0-9.]+)\]"
        for match in re.finditer(pattern, text):
            start, speaker, body, end = match.groups()
            text_content = (body or "").strip()
            if not text_content:
                continue
            segments.append(
                SpeakerSegment(
                    speaker=self.map_speaker_label(speaker),
                    start_time=float(start),
                    end_time=float(end),
                    text=text_content,
                )
            )
        return segments

    def map_speaker_label(self, label: str | int) -> str:
        """Map [S01]/Sxx labels to Speaker N for consistent UI."""
        if isinstance(label, int):
            return f"{self.speaker_prefix} {label}"
        s = str(label).strip()
        # [S01] or S01 → Speaker 1
        import re
        m = re.fullmatch(r"\[?S0*(\d+)\]?", s, flags=re.IGNORECASE)
        if m:
            return f"{self.speaker_prefix} {int(m.group(1))}"
        return super().map_speaker_label(label)
