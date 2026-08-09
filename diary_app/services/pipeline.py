"""STT session pipeline: record → transcribe → analyze → persist → index → side effects.

Each step is independent so callers can re-analyze without re-STT, etc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from diary_app.config import get_config
from diary_app.core.logutil import emit_progress, get_logger, is_cancelled, CancelledError
from diary_app.core.registry import create_analyzer, create_backend
from diary_app.core.store import EntryStore, get_store
from diary_app.domain.models import KeyPoints, Transcript

log = get_logger("pipeline")


@dataclass
class PipelineResult:
    """Outcome of a full or partial pipeline run."""

    ok: bool = True
    error: str | None = None
    wav_path: str | None = None
    entry_id: str | None = None
    transcript_path: str | None = None
    analysis_path: str | None = None
    audio_path: str | None = None
    transcript: dict | None = None
    key_points: dict | None = None
    warnings: list[str] = field(default_factory=list)
    backend: str | None = None
    device: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"ok": self.ok}
        if self.error:
            d["error"] = self.error
        for k in (
            "wav_path",
            "entry_id",
            "transcript_path",
            "analysis_path",
            "audio_path",
            "transcript",
            "key_points",
            "warnings",
            "backend",
            "device",
        ):
            v = getattr(self, k)
            if v is not None and v != []:
                d[k] = v
        return d


def record_audio(
    *,
    duration: float | None = None,
    diary_dir: Path | None = None,
    silence_stop: bool = False,
    device_id: int | None = None,
) -> Path:
    """Step: capture microphone → WAV path."""
    from diary_app.core.audio import AudioConfig

    cfg = get_config()
    root = Path(diary_dir) if diary_dir else Path(cfg.diary_dir)
    root.mkdir(parents=True, exist_ok=True)
    duration = float(duration or 30)
    emit_progress("record", 0.0, "Starting recording")

    def progress(frac: float, status: str) -> None:
        emit_progress("record", frac, status)

    config = AudioConfig(
        max_duration=max(10, int(duration)),
        device=device_id,
    )
    if silence_stop:
        audio = config.record_until_silence(progress_callback=progress)
    else:
        audio = config.record(duration=duration, progress_callback=progress)
    if audio.size == 0:
        raise RuntimeError("No audio recorded")
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    wav_path = root / f"recording_{ts}.wav"
    config.save_wav(audio, wav_path)
    emit_progress("record", 1.0, f"Saved {wav_path}")
    return wav_path.resolve()


def transcribe_file(
    wav_path: Path | str,
    *,
    backend: str | None = None,
    device: str | None = None,
    max_speakers: int | None = None,
    model_size: str | None = None,
    backend_instance: Any | None = None,
) -> tuple[Transcript, str, str]:
    """
    Step: audio → Transcript.

    Returns (transcript, backend_name, device_label).
    Pass backend_instance to reuse a warm model (Gradio / daemon).
    """
    cfg = get_config()
    wav = Path(wav_path).expanduser().resolve()
    if not wav.exists():
        raise FileNotFoundError(f"Audio file not found: {wav}")

    backend_name = (backend or cfg.default_backend or "auto").lower()
    device = device or cfg.default_device
    max_speakers = max_speakers if max_speakers is not None else cfg.max_speakers

    emit_progress("transcribe", 0.05, f"Loading backend {backend_name}")
    if is_cancelled():
        raise CancelledError()

    if backend_instance is not None:
        be = backend_instance
    else:
        be = create_backend(
            backend_name,
            device=device,
            max_speakers=max_speakers,
            model_size=model_size,
        )
    resolved_name = getattr(be, "name", backend_name) or backend_name

    emit_progress("transcribe", 0.2, f"Transcribing {wav.name}")
    transcript = be.transcribe(wav)

    # Normalize to domain Transcript if backend returned legacy type
    if not isinstance(transcript, Transcript):
        if hasattr(transcript, "to_json"):
            transcript = Transcript.from_json(transcript.to_json())
        else:
            raise TypeError("Backend returned unknown transcript type")

    device_label = device
    try:
        from diary_app.core.device import resolve_torch_device

        device_label = resolve_torch_device(device).details
    except Exception:
        pass

    emit_progress("transcribe", 0.75, "Transcription complete")
    return transcript, resolved_name, device_label


def analyze_transcript(
    transcript: Transcript,
    *,
    analyzer_name: str | None = None,
) -> KeyPoints:
    """Step: Transcript → KeyPoints."""
    emit_progress("analyze", 0.8, "Analyzing")
    if is_cancelled():
        raise CancelledError()
    analyzer = create_analyzer(analyzer_name)
    kp = analyzer.analyze(transcript)
    if not isinstance(kp, KeyPoints):
        if hasattr(kp, "to_json"):
            kp = KeyPoints.from_json(kp.to_json())
    emit_progress("analyze", 0.9, "Analysis complete")
    return kp


def persist_entry(
    transcript: Transcript,
    key_points: KeyPoints | None,
    *,
    audio_path: Path | str | None = None,
    diary_dir: Path | None = None,
    backend: str | None = None,
    device: str | None = None,
    entry_id: str | None = None,
    store: EntryStore | None = None,
) -> Any:
    """Step: write history entry + index."""
    emit_progress("persist", 0.92, "Saving entry")
    st = store or get_store(diary_dir)
    entry = st.save_bundle(
        transcript,
        key_points,
        audio_path=audio_path,
        backend=backend,
        device=device,
        entry_id=entry_id,
    )
    emit_progress("persist", 0.96, f"Saved {entry.id}")
    return entry


def sync_actions(diary_dir: Path | None = None) -> int:
    """Side effect: pull action items into inbox."""
    try:
        from diary_app.core.actions import ActionInbox
        from diary_app.config import get_config

        root = Path(diary_dir) if diary_dir else Path(get_config().diary_dir)
        return ActionInbox(root).sync_from_history()
    except Exception as e:
        log.debug("action sync skipped: %s", e)
        return 0


def run_session(
    *,
    audio_path: Path | str | None = None,
    record_duration: float | None = None,
    backend: str | None = None,
    device: str | None = None,
    diary_dir: Path | None = None,
    analyze: bool = True,
    persist: bool = True,
    sync_action_inbox: bool = True,
    silence_stop: bool = False,
    max_speakers: int | None = None,
    model_size: str | None = None,
    backend_instance: Any | None = None,
) -> PipelineResult:
    """
    Full pipeline orchestration.

    Provide audio_path *or* record_duration (to record first).
    Pass backend_instance to reuse a warm model without reloading.
    """
    cfg = get_config()
    root = Path(diary_dir) if diary_dir else Path(cfg.diary_dir)
    store = get_store(root)

    try:
        wav: Path
        if audio_path:
            wav = Path(audio_path).expanduser().resolve()
        else:
            wav = record_audio(
                duration=record_duration,
                diary_dir=root,
                silence_stop=silence_stop,
            )

        transcript, backend_name, device_label = transcribe_file(
            wav,
            backend=backend,
            device=device,
            max_speakers=max_speakers,
            model_size=model_size,
            backend_instance=backend_instance,
        )
        kp: KeyPoints | None = None
        if analyze:
            kp = analyze_transcript(transcript)

        entry = None
        if persist:
            entry = persist_entry(
                transcript,
                kp,
                audio_path=wav,
                diary_dir=root,
                backend=backend_name,
                device=device_label,
                store=store,
            )
            if sync_action_inbox:
                sync_actions(root)

        emit_progress("done", 1.0, "Complete")
        return PipelineResult(
            ok=True,
            wav_path=str(wav),
            entry_id=entry.id if entry else None,
            transcript_path=entry.transcript_path if entry else None,
            analysis_path=entry.analysis_path if entry else None,
            audio_path=entry.audio_path if entry else str(wav),
            transcript=transcript.to_json(),
            key_points=kp.to_json() if kp else None,
            warnings=list(transcript.warnings or []),
            backend=backend_name,
            device=device_label,
        )
    except CancelledError as e:
        return PipelineResult(ok=False, error=str(e))
    except Exception as e:
        log.exception("pipeline failed")
        return PipelineResult(ok=False, error=str(e))
