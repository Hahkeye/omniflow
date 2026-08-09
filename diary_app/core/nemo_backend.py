"""NeMo-based transcription backend for NVIDIA GPUs (optional).

Uses the Parakeet 0.6B multitalker ASR model with Sortformer
diarization for offline transcription.
"""

from __future__ import annotations

import gc
from pathlib import Path

from .transcribe import BaseTranscriptionBackend, Transcript, SpeakerSegment

DIAR_MODEL_ID = "nvidia/diar_streaming_sortformer_4spk-v2.1"
ASR_MODEL_ID = "nvidia/multitalker-parakeet-streaming-0.6b-v1"

_models: dict = {"diar": None, "asr": None}

HAS_NEMO = False
_NEMO_IMPORT_ERROR: str | None = None

try:
    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel
    from nemo.collections.asr.models import EncDecMultiTalkerRNNTBPEModel as ASRModel
    from nemo.collections.asr.parts.utils.multispk_transcribe_utils import MultiTalkerInstanceManager

    if hasattr(MultiTalkerInstanceManager, "transcribe_multitalker"):
        HAS_NEMO = True
    else:
        _NEMO_IMPORT_ERROR = (
            "Installed NeMo is missing MultiTalkerInstanceManager.transcribe_multitalker"
        )
except ImportError as e:
    HAS_NEMO = False
    _NEMO_IMPORT_ERROR = str(e)
    torch = None  # type: ignore


def get_device():
    """Get the best available CUDA device."""
    if torch is not None and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu") if torch is not None else None


class NeMoBackend(BaseTranscriptionBackend):
    """NeMo multitalker offline ASR backend for NVIDIA GPUs (optional)."""

    name = "nemo"
    description = "NeMo Parakeet 0.6B (4-speaker offline, NVIDIA GPU) [optional]"

    def __init__(self, max_speakers: int = 4, warmup: bool = True, model_size: str | None = None):
        # model_size accepted for Gradio API compatibility; NeMo uses fixed models
        del model_size
        if not HAS_NEMO:
            raise RuntimeError(
                "NeMo not available.\n"
                f"  Detail: {_NEMO_IMPORT_ERROR or 'not installed'}\n"
                "  Install (Linux/Windows + CUDA only):\n"
                "    pip install -r diary_app/requirements-nemo.txt"
            )
        if not torch.cuda.is_available():
            raise RuntimeError(
                "NVIDIA GPU not found. NeMo backend requires CUDA."
            )
        super().__init__(max_speakers)
        self.device = get_device()
        self._max_speakers = max_speakers
        if warmup:
            self.warmup()

    def warmup(self) -> None:
        """Warm up models — downloads weights and initializes GPU."""
        print(f"Loading diarization model: {DIAR_MODEL_ID}...")
        if _models["diar"] is None:
            _models["diar"] = SortformerEncLabelModel.from_pretrained(DIAR_MODEL_ID)
            _models["diar"] = _models["diar"].eval().to(self.device)
        if _models["asr"] is None:
            print(f"Loading ASR model: {ASR_MODEL_ID}...")
            _models["asr"] = ASRModel.from_pretrained(ASR_MODEL_ID)
            _models["asr"] = _models["asr"].eval().to(self.device)

        _ = torch.randn(1, 80, 100, device=self.device)
        if self.device.type == "cuda":
            torch.cuda.synchronize()
        print("Models ready.")

    def unload(self) -> None:
        _models["diar"] = None
        _models["asr"] = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

    def transcribe(self, wav_path: Path) -> Transcript:
        """Transcribe audio file using NeMo multitalker ASR pipeline."""
        wav_path = Path(wav_path).resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")

        print(f"Transcribing: {wav_path}")
        samples = [{"audio_filepath": str(wav_path)}]

        diar_model = _models["diar"]
        asr_model = _models["asr"]
        if diar_model is None or asr_model is None:
            self.warmup()
            diar_model = _models["diar"]
            asr_model = _models["asr"]

        diar_model = diar_model.eval().to(self.device)
        asr_model = asr_model.eval().to(self.device)

        instance_manager = MultiTalkerInstanceManager(
            asr_model=asr_model,
            diar_model=diar_model,
            device=self.device,
            max_speakers=self._max_speakers,
        )

        print("Running diarization + transcription...")
        result = instance_manager.transcribe_multitalker(
            samples=samples,
            diar_model=diar_model,
            asr_model=asr_model,
            device=self.device,
        )

        print("Parsing results...")
        segments = self._parse_results(result, samples)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

        return Transcript(segments=segments)

    def _parse_results(self, result, samples) -> list[SpeakerSegment]:
        """Parse NeMo multitalker transcription results into SpeakerSegments."""
        segments: list[SpeakerSegment] = []

        for i, _sample in enumerate(samples):
            if isinstance(result, list):
                if i >= len(result):
                    break
                seglst = result[i]
            else:
                seglst = result

            if not isinstance(seglst, dict):
                continue

            for start_ms, seg in seglst.items():
                if not seg or "spk" not in seg:
                    continue

                try:
                    start_s = float(start_ms) / 1000.0
                except (TypeError, ValueError):
                    start_s = float(seg.get("start", 0.0))
                    if start_s > 1000:
                        start_s /= 1000.0

                end_raw = seg.get("end", start_s + 1.0)
                end_s = float(end_raw)
                if end_s > 1000 and end_s > start_s * 10:
                    # Heuristic: some APIs return ms
                    end_s = end_s / 1000.0

                text = seg.get("text", seg.get("word", ""))
                speaker = self.map_speaker_label(seg["spk"])

                if text and str(text).strip():
                    segments.append(
                        SpeakerSegment(
                            speaker=speaker,
                            start_time=start_s,
                            end_time=end_s,
                            text=str(text).strip(),
                        )
                    )

        segments.sort(key=lambda s: s.start_time)
        return segments
