"""Audio feedback for cStrafe UI.

Tones are synthesised at startup into temp WAV files (no extra dependencies)
and played asynchronously so they never block input handling.

  Perfect        -> bright, sparkly rising major arpeggio
  Good           -> soft two-note ping
  Bad            -> quiet, neutral low "bop" (not a warning sound)
  Overlap        -> two mid-pitch beeps
  Standing / Crouching -> silent

Run `python audio.py` to hear every sound.
"""
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from typing import Dict, List, Tuple

# segments: (frequency Hz, duration ms); frequency 0 = silence
# harmonics: (multiple of the base frequency, relative loudness) for a brighter / bell-like tone
# decay: exponential fall-off per segment (0 = flat); gain: overall loudness of this sound
SOUNDS: Dict[str, dict] = {
    "Perfect": {
        "segments": [(1319, 60), (1568, 60), (2093, 60), (2637, 220)],  # E6 G6 C7 E7
        "harmonics": [(2, 0.35), (3, 0.15)],
        "decay": 2.2,
        "gain": 1.0,
    },
    "Good": {
        "segments": [(880, 70), (1175, 110)],
        "harmonics": [(2, 0.2)],
        "decay": 1.5,
        "gain": 0.9,
    },
    "Bad": {
        "segments": [(294, 110)],  # a single soft low tone, no harsh edge
        "harmonics": [(2, 0.1)],
        "decay": 4.0,
        "gain": 0.7,
    },
    "Overlap": {
        "segments": [(660, 60), (0, 40), (660, 60)],
        "harmonics": [],
        "decay": 0.0,
        "gain": 0.9,
    },
}

SAMPLE_RATE = 44100
VOLUME = 0.35


def _render(spec: dict) -> bytes:
    harmonics: List[Tuple[int, float]] = spec["harmonics"]
    norm = 1.0 + sum(a for _, a in harmonics)
    frames = bytearray()
    for freq, ms in spec["segments"]:
        n = int(SAMPLE_RATE * ms / 1000)
        fade = min(int(SAMPLE_RATE * 0.004), n // 2)  # short fades avoid clicks
        for i in range(n):
            if freq == 0:
                s = 0.0
            else:
                w = 2 * math.pi * freq * i / SAMPLE_RATE
                s = math.sin(w) + sum(a * math.sin(w * m) for m, a in harmonics)
                s /= norm
                if spec["decay"]:
                    s *= math.exp(-spec["decay"] * i / n)
            env = 1.0
            if fade:
                env = min(1.0, i / fade, (n - 1 - i) / fade)
            frames += struct.pack("<h", int(s * env * spec["gain"] * VOLUME * 32767))
    return bytes(frames)


class AudioFeedback:
    def __init__(self) -> None:
        self.enabled = True
        self._dir = tempfile.mkdtemp(prefix="cstrafe_audio_")
        self._files: Dict[str, str] = {}
        for i, (label, spec) in enumerate(SOUNDS.items()):
            path = os.path.join(self._dir, f"{i}.wav")
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(_render(spec))
            self._files[label] = path

        self._player = None
        if sys.platform == "win32":
            import winsound  # noqa: F401
            self._player = "winsound"
        elif sys.platform == "darwin":
            self._player = "afplay"
        else:
            self._player = next((p for p in ("paplay", "aplay") if shutil.which(p)), None)

    def play(self, label: str) -> None:
        if not self.enabled or self._player is None:
            return
        path = self._files.get(label)
        if path is None:
            return
        try:
            if self._player == "winsound":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                subprocess.Popen(
                    [self._player, path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def cleanup(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)


if __name__ == "__main__":
    fb = AudioFeedback()
    try:
        for name in SOUNDS:
            print(f"Playing: {name}")
            fb.play(name)
            time.sleep(1.2)
    finally:
        fb.cleanup()
