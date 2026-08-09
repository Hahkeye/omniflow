"""Audio capture and recording module."""
from __future__ import annotations

import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np
from pydantic import BaseModel, Field

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM

ProgressCallback = Callable[[float, str], None]


def _sounddevice():
    """Lazy import so CLI can transcribe without PortAudio installed."""
    try:
        import sounddevice as sd
    except OSError as e:
        raise RuntimeError(
            "sounddevice/PortAudio is not available. "
            "Install PortAudio (e.g. apt install libportaudio2 / brew install portaudio) "
            "or use file-based transcription without recording."
        ) from e
    return sd


class AudioConfig(BaseModel):
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    sample_width: int = SAMPLE_WIDTH
    max_duration: int = Field(default=300, ge=10, le=3600)
    silence_threshold: float = Field(default=0.03, ge=0.01, le=0.1)
    silence_duration: float = Field(default=2.0, ge=1.0, le=5.0)
    fade_in_s: float = Field(default=0.1, ge=0.0, le=0.5)
    fade_out_s: float = Field(default=0.2, ge=0.0, le=0.5)
    # sounddevice device index; None uses the system default input
    device: int | None = None

    @property
    def dtype(self) -> np.dtype:
        return np.int16 if self.sample_width == 2 else np.int32

    def save_wav(self, audio: np.ndarray, path: Path) -> None:
        """Write mono PCM WAV. Accepts float [-1, 1] or int16 samples."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        arr = np.asarray(audio)
        if arr.ndim > 1:
            arr = arr.reshape(-1)

        if np.issubdtype(arr.dtype, np.floating):
            arr = np.clip(arr, -1.0, 1.0)
            pcm = (arr * np.iinfo(np.int16).max).astype(np.int16)
        elif arr.dtype == np.int16:
            pcm = arr
        else:
            pcm = np.clip(arr, np.iinfo(np.int16).min, np.iinfo(np.int16).max).astype(np.int16)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm.tobytes())

    def _rec_kwargs(self) -> dict:
        kwargs: dict = {
            "samplerate": self.sample_rate,
            "channels": self.channels,
            "dtype": np.int16,
        }
        if self.device is not None:
            kwargs["device"] = self.device
        return kwargs

    def record(
        self,
        duration: float | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> np.ndarray:
        sd = _sounddevice()
        duration = float(duration or self.max_duration)
        if progress_callback:
            progress_callback(0.0, f"Recording for {int(duration)}s...")
        print("Recording... Press Ctrl+C to stop early")

        remaining = duration
        audio_parts: list[np.ndarray] = []
        try:
            while remaining > 0:
                chunk_s = min(1.0, remaining)
                frames = max(1, int(round(chunk_s * self.sample_rate)))
                chunk = sd.rec(frames, **self._rec_kwargs())
                sd.wait()
                audio_parts.append(chunk.flatten())
                remaining = max(0.0, remaining - chunk_s)
                elapsed = duration - remaining
                if progress_callback:
                    progress_callback(
                        elapsed / duration if duration else 1.0,
                        f"Recording... {int(elapsed)}s",
                    )
        except KeyboardInterrupt:
            if progress_callback:
                progress_callback(0.5, "Recording interrupted — saving what we have")

        result = np.concatenate(audio_parts) if audio_parts else np.array([], dtype=np.int16)
        if progress_callback and result.size > 0:
            progress_callback(1.0, f"Recording saved ({len(result)} samples)")
        return result

    def record_until_silence(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> np.ndarray:
        """Record until silence is detected for silence_duration seconds after speech."""
        sd = _sounddevice()
        if progress_callback:
            progress_callback(0.0, "Listening... Press Ctrl+C to stop")

        audio_parts: list[np.ndarray] = []
        silence_seconds = 0.0
        heard_speech = False
        frames = max(1, int(round(self.silence_duration * self.sample_rate)))
        energy_threshold = self.silence_threshold * np.iinfo(np.int16).max

        try:
            while True:
                chunk = sd.rec(frames, **self._rec_kwargs())
                sd.wait()
                chunk_flat = chunk.flatten()
                energy = float(np.mean(np.abs(chunk_flat.astype(np.float64))))
                chunk_duration = len(chunk_flat) / self.sample_rate

                if energy > energy_threshold:
                    heard_speech = True
                    silence_seconds = 0.0
                    audio_parts.append(chunk_flat)
                    if progress_callback:
                        elapsed = sum(len(p) for p in audio_parts) / self.sample_rate
                        progress_callback(0.5, f"Recording... {int(elapsed)}s")
                else:
                    if heard_speech:
                        audio_parts.append(chunk_flat)
                        silence_seconds += chunk_duration
                        if progress_callback:
                            progress_callback(
                                0.8,
                                f"Silence... ({silence_seconds:.1f}s)",
                            )
                        if silence_seconds >= self.silence_duration:
                            if progress_callback:
                                progress_callback(1.0, "Silence detected — recording stopped")
                            break
                    else:
                        if progress_callback:
                            progress_callback(0.1, "Waiting for speech...")
        except KeyboardInterrupt:
            if progress_callback:
                progress_callback(0.5, "Recording interrupted — saving what we have")

        return np.concatenate(audio_parts) if audio_parts else np.array([], dtype=np.int16)


# ─── Interactive session (start / pause / resume / stop) ─────────────────────

class InteractiveRecorder:
    """
    Background microphone capture with pause/resume/stop.

    Designed for daemon + desktop hotkeys: start once, control from the UI
    without blocking the request thread on full duration.
    """

    def __init__(
        self,
        config: AudioConfig | None = None,
        *,
        chunk_seconds: float = 0.25,
        max_duration: float = 3600.0,
    ):
        self.config = config or AudioConfig()
        self.chunk_seconds = max(0.05, float(chunk_seconds))
        self.max_duration = float(max_duration)
        self._parts: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pause = threading.Event()  # set ⇒ paused
        self._thread: threading.Thread | None = None
        self._state = "idle"  # idle | recording | paused | stopped
        self._started_at: float | None = None
        self._elapsed_s = 0.0
        self._error: str | None = None

    @property
    def state(self) -> str:
        return self._state

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "elapsed_s": round(self._elapsed_s, 2),
                "samples": int(sum(len(p) for p in self._parts)),
                "error": self._error,
            }

    def start(self) -> dict:
        with self._lock:
            if self._state in ("recording", "paused"):
                raise RuntimeError(f"Already {self._state}")
            self._parts = []
            self._error = None
            self._elapsed_s = 0.0
            self._stop.clear()
            self._pause.clear()
            self._started_at = time.time()
            self._state = "recording"
            self._thread = threading.Thread(
                target=self._capture_loop, name="omniflow-recorder", daemon=True
            )
            self._thread.start()
        return self.status()

    def pause(self) -> dict:
        with self._lock:
            if self._state != "recording":
                raise RuntimeError(f"Cannot pause from state={self._state}")
            self._pause.set()
            self._state = "paused"
        return self.status()

    def resume(self) -> dict:
        with self._lock:
            if self._state != "paused":
                raise RuntimeError(f"Cannot resume from state={self._state}")
            self._pause.clear()
            self._state = "recording"
        return self.status()

    def stop(self) -> tuple[np.ndarray, dict]:
        """Stop capture and return (pcm_int16, status)."""
        with self._lock:
            if self._state == "idle":
                raise RuntimeError("Not recording")
            self._stop.set()
            self._pause.clear()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=15.0)
        with self._lock:
            self._state = "stopped"
            audio = (
                np.concatenate(self._parts)
                if self._parts
                else np.array([], dtype=np.int16)
            )
            status = {
                "state": self._state,
                "elapsed_s": round(self._elapsed_s, 2),
                "samples": int(audio.size),
                "error": self._error,
            }
            # reset for next session
            self._thread = None
            self._state = "idle"
            self._parts = []
            return audio, status

    def cancel(self) -> dict:
        """Stop and discard audio."""
        try:
            audio, status = self.stop()
            status["discarded"] = True
            status["samples"] = 0
            return status
        except RuntimeError:
            return {"state": "idle", "elapsed_s": 0, "samples": 0, "discarded": True}

    def _capture_loop(self) -> None:
        try:
            sd = _sounddevice()
            frames = max(1, int(round(self.chunk_seconds * self.config.sample_rate)))
            while not self._stop.is_set():
                if self._pause.is_set():
                    time.sleep(0.05)
                    continue
                if self._elapsed_s >= self.max_duration:
                    break
                chunk = sd.rec(frames, **self.config._rec_kwargs())
                sd.wait()
                flat = chunk.flatten()
                with self._lock:
                    self._parts.append(flat)
                    self._elapsed_s += len(flat) / float(self.config.sample_rate)
        except Exception as e:
            with self._lock:
                self._error = str(e)
                self._state = "stopped"


# Process-wide session for daemon / API (one interactive recording at a time)
_session_lock = threading.Lock()
_session: InteractiveRecorder | None = None


def interactive_status() -> dict:
    with _session_lock:
        if _session is None:
            return {"state": "idle", "elapsed_s": 0, "samples": 0, "error": None}
        return _session.status()


def interactive_start(
    *,
    device: int | None = None,
    max_duration: float = 3600.0,
) -> dict:
    global _session
    with _session_lock:
        if _session is not None and _session.state in ("recording", "paused"):
            raise RuntimeError("Recording already in progress")
        cfg = AudioConfig(device=device, max_duration=max(10, int(max_duration)))
        _session = InteractiveRecorder(cfg, max_duration=max_duration)
        return _session.start()


def interactive_pause() -> dict:
    with _session_lock:
        if _session is None:
            raise RuntimeError("No active recording")
        return _session.pause()


def interactive_resume() -> dict:
    with _session_lock:
        if _session is None:
            raise RuntimeError("No active recording")
        return _session.resume()


def interactive_stop(*, diary_dir: Path | None = None) -> dict:
    """Stop session, write WAV under diary_dir, return path + status."""
    global _session
    from datetime import datetime
    from diary_app.config import get_diary_dir

    with _session_lock:
        if _session is None:
            raise RuntimeError("No active recording")
        rec = _session
        audio, status = rec.stop()
        _session = None

    if audio.size == 0:
        return {**status, "wav_path": None, "error": status.get("error") or "No audio captured"}

    root = Path(diary_dir) if diary_dir else get_diary_dir()
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    wav_path = root / f"recording_{ts}.wav"
    AudioConfig().save_wav(audio, wav_path)
    return {
        **status,
        "wav_path": str(wav_path.resolve()),
        "duration_s": status.get("elapsed_s"),
    }


def interactive_cancel() -> dict:
    global _session
    with _session_lock:
        if _session is None:
            return {"state": "idle", "discarded": True}
        status = _session.cancel()
        _session = None
        return status
