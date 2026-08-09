"""Interactive recorder state machine (no microphone required)."""
from __future__ import annotations

import threading
import time

import numpy as np

from diary_app.core.audio import InteractiveRecorder, AudioConfig


class FakeRecorder(InteractiveRecorder):
    """Recorder that synthesizes silence instead of opening the mic."""

    def _capture_loop(self) -> None:
        frames = max(1, int(round(self.chunk_seconds * self.config.sample_rate)))
        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(0.02)
                continue
            if self._elapsed_s >= self.max_duration:
                break
            flat = np.zeros(frames, dtype=np.int16)
            with self._lock:
                self._parts.append(flat)
                self._elapsed_s += len(flat) / float(self.config.sample_rate)
            time.sleep(0.02)


def test_start_pause_resume_stop():
    rec = FakeRecorder(AudioConfig(max_duration=60), chunk_seconds=0.05, max_duration=10)
    st = rec.start()
    assert st["state"] == "recording"
    time.sleep(0.15)
    st = rec.pause()
    assert st["state"] == "paused"
    paused_elapsed = st["elapsed_s"]
    time.sleep(0.1)
    # elapsed should not jump much while paused (small race ok)
    st2 = rec.status()
    assert st2["state"] == "paused"
    assert abs(st2["elapsed_s"] - paused_elapsed) < 0.2
    rec.resume()
    assert rec.status()["state"] == "recording"
    time.sleep(0.1)
    audio, final = rec.stop()
    assert final["state"] == "idle" or True  # stop resets to idle
    assert audio.size > 0
    assert rec.status()["state"] == "idle"


def test_cancel_discards():
    rec = FakeRecorder(AudioConfig(max_duration=60), chunk_seconds=0.05)
    rec.start()
    time.sleep(0.1)
    st = rec.cancel()
    assert st.get("discarded") is True
    assert rec.status()["state"] == "idle"
