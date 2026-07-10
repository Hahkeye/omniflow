"""Audio capture and recording module."""
import wave
import io
import numpy as np
import sounddevice as sd
from pathlib import Path
from pydantic import BaseModel, Field

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM
MAX_DURATIONS = [60, 120, 300, 600, 1800]  # preset durations in seconds


class AudioConfig(BaseModel):
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    sample_width: int = SAMPLE_WIDTH
    max_duration: int = Field(default=300, ge=10, le=3600)
    silence_threshold: float = Field(default=0.03, ge=0.01, le=0.1)
    silence_duration: float = Field(default=2.0, ge=1.0, le=5.0)
    fade_in_s: float = Field(default=0.1, ge=0.0, le=0.5)
    fade_out_s: float = Field(default=0.2, ge=0.0, le=0.5)

    @property
    def dtype(self) -> np.dtype:
        return np.int16 if self.sample_width == 2 else np.int32

    @property
    def wav_format(self) -> int:
        return 1  # PCM

    def to_wav_bytes(self, audio: np.ndarray) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes((audio * np.iinfo(np.int16).max).astype(np.int16).tobytes())
        return buf.getvalue()

    def save_wav(self, audio: np.ndarray, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes((audio * np.iinfo(np.int16).max).astype(np.int16).tobytes())

    def save_wav_bytes(self, wav_bytes: bytes, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav_bytes)

    def audio_to_wav(self, audio: np.ndarray) -> bytes:
        return self.to_wav_bytes(audio)

    def wav_bytes_to_audio(self, wav_bytes: bytes) -> np.ndarray:
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        return np.frombuffer(raw, dtype=np.int16) / np.iinfo(np.int16).max

    def record(self, duration: float | None = None, progress_callback=None) -> np.ndarray:
        duration = duration or self.max_duration
        if progress_callback:
            progress_callback(0.0, f"Recording for {int(duration)}s...")
        print("Recording... Press Ctrl+C to stop early")
        total = int(duration)
        audio_parts = []
        try:
            while total > 0:
                chunk = sd.rec(int(min(1.0, total)), samplerate=self.sample_rate,
                              channels=self.channels, dtype=np.int16)
                sd.wait()
                audio_parts.append(chunk.flatten())
                elapsed = duration - total
                total = max(0, total - 1)
                if progress_callback:
                    progress_callback(elapsed / duration, f"Recording... {int(duration - total)}s")
        except KeyboardInterrupt:
            if progress_callback:
                progress_callback(0.5, "Recording interrupted — saving what we have")
        result = np.concatenate(audio_parts) if audio_parts else np.array([])
        if progress_callback and result.size > 0:
            progress_callback(1.0, f"Recording saved ({len(result)} samples)")
        return result

    def record_until_silence(self, progress_callback=None) -> np.ndarray:
        """Record until silence is detected for silence_duration seconds."""
        if progress_callback:
            progress_callback(0.0, "Listening... Press Ctrl+C to stop")
        audio_parts = []
        silence_count = 0
        is_silence = True
        last_speech_time = 0

        try:
            while True:
                chunk = sd.rec(int(self.silence_duration * 1000), samplerate=self.sample_rate,
                              channels=self.channels, dtype=np.int16)
                sd.wait()
                chunk_flat = chunk.flatten()
                energy = np.mean(np.abs(chunk_flat))

                if energy > self.silence_threshold:
                    if is_silence and audio_parts:
                        # Switch from silence to speech
                        is_silence = False
                        if progress_callback:
                            progress_callback(0.3, "Speech detected")
                    if not is_silence:
                        last_speech_time = silence_count * self.silence_duration
                    audio_parts.append(chunk_flat)
                    silence_count = 0
                    is_silence = False
                else:
                    if is_silence:
                        silence_count += 1
                        if progress_callback:
                            progress_callback(0.3 + (silence_count / 30), f"Silence... ({silence_count}s)")
                        if silence_count * self.silence_duration >= self.silence_duration and audio_parts:
                            if progress_callback:
                                progress_callback(1.0, "Silence detected — recording stopped")
                            break
                if progress_callback:
                    elapsed = len(audio_parts) * self.silence_duration
                    progress_callback(0.5, f"Recording... {int(elapsed)}s")
        except KeyboardInterrupt:
            if progress_callback:
                progress_callback(0.5, "Recording interrupted — saving what we have")
        result = np.concatenate(audio_parts) if audio_parts else np.array([])
        return result
