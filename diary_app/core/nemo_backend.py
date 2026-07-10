"""NeMo-based transcription backend for NVIDIA GPUs (RTX 5080+).

Uses the Parakeet 0.6B multitalker ASR model with Sortformer
diarization for offline transcription. One ASR instance per speaker
(up to 4) for maximum accuracy with overlapping speech.
"""
import gc
import time
import numpy as np
from pathlib import Path
from typing import Optional

import torch

from .transcribe import BaseTranscriptionBackend, Transcript, SpeakerSegment

# Models
DIAR_MODEL_ID = "nvidia/diar_streaming_sortformer_4spk-v2.1"
ASR_MODEL_ID = "nvidia/multitalker-parakeet-streaming-0.6b-v1"

# Model cache
_models = {"diar": None, "asr": None}

try:
    from nemo.collections.asr.models import SortformerEncLabelModel
    from nemo.collections.asr.models import EncDecMultiTalkerRNNTBPEModel as ASRModel
    from nemo.collections.asr.parts.utils.multispk_transcribe_utils import SpeakerTaggedASR, MultiTalkerInstanceManager
    if not hasattr(MultiTalkerInstanceManager, 'transcribe_multitalker'):
        HAS_NEMO = False
except ImportError:
    HAS_NEMO = False

def get_device():
    """Get the best available device."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")

class NeMoBackend(BaseTranscriptionBackend):
    """NeMo multitalker offline ASR backend for RTX GPUs."""

    name = "nemo"
    description = "NeMo Parakeet 0.6B (4-speaker offline, NVIDIA GPU required) [EXPERIMENTAL]"

    def __init__(self, max_speakers: int = 4, warmup: bool = True):
        if not HAS_NEMO:
            raise RuntimeError(
                "NeMo not installed. Install with:\n"
                "  pip install 'nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@main'"
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

        # Warm up GPU
        _ = torch.randn(1, 80, 100).cuda()
        torch.cuda.synchronize()
        print("Models ready.")

    def transcribe(self, wav_path: Path) -> Transcript:
        """Transcribe audio file using NeMo multitalker ASR pipeline."""
        wav_path = Path(wav_path).resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")

        print(f"Transcribing: {wav_path}")
        samples = [{"audio_filepath": str(wav_path)}]

        # Initialize diarization model
        diar_model = _models["diar"]
        diar_model = diar_model.eval().to(self.device)

        # Initialize ASR model with speaker count
        asr_model = _models["asr"]
        asr_model = asr_model.eval().to(self.device)

        # Setup multitalker ASR
        instance_manager = MultiTalkerInstanceManager(
            asr_model=asr_model,
            diar_model=diar_model,
            device=self.device,
            max_speakers=self._max_speakers,
        )

        # Perform transcription
        print("Running diarization + transcription...")
        result = instance_manager.transcribe_multitalker(
            samples=samples,
            diar_model=diar_model,
            asr_model=asr_model,
            device=self.device,
        )

        # Parse results
        print("Parsing results...")
        segments = self._parse_results(result, samples)

        # Clean up GPU memory
        torch.cuda.empty_cache()
        gc.collect()

        return Transcript(segments=segments)

    def _parse_results(self, result, samples) -> list[SpeakerSegment]:
        """Parse NeMo multitalker transcription results into SpeakerSegments."""
        segments = []

        # The result should be a list of seglst dicts
        # Each entry corresponds to one audio file
        for i, sample in enumerate(samples):
            if i >= len(result):
                break
            seglst = result[i] if isinstance(result, list) else result

            if not isinstance(seglst, dict):
                continue

            for start_ms, seg in seglst.items():
                if not seg or "spk" not in seg:
                    continue

                start_s = start_ms / 1000.0
                end_s = seg.get("end", start_s + 1.0)

                # Get text from NeMo
                text = seg.get("text", seg.get("word", ""))

                # Get speaker
                speaker_label = seg["spk"]
                speaker = self.map_speaker_label(speaker_label)

                if text.strip():
                    segments.append(SpeakerSegment(
                        speaker=speaker,
                        start_time=start_s,
                        end_time=end_s,
                        text=text.strip(),
                    ))

        segments.sort(key=lambda s: s.start_time)
        return segments
