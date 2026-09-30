from dataclasses import dataclass, field
from typing import Optional, Tuple

# ---- Tunable thresholds (ms) ----
MAX_SHOT_DELAY = 230.0      # slower than this = "Bad"
MAX_SLOW_BOTH = 215.0       # cs_time AND shot_delay both above this = "Bad"
PERFECT_CS_MAX = 50.0       # perfect: opposite key pressed almost instantly after release ...
PERFECT_DELAY_MAX = 110.0   # ... and shot fired within this many ms of that press
SLOW_STOP_MAX = 1000.0      # released-with-no-counter older than this counts as plain "Bad"
OVERLAP_MIN_MS = 25.0       # shorter overlaps are a "swap" (press new key just before lifting old): an instant counter-strafe, not Overlap
OVERLAP_MEMORY_MS = 250.0   # a finished overlap only counts if it ended this recently before the shot


@dataclass
class AxisState:
    keys: Tuple[str, str]
    held_keys: set = field(default_factory=set)
    press_times: dict = field(default_factory=dict)
    cs_release_key: Optional[str] = None
    cs_release_time: Optional[float] = None
    cs_press_key: Optional[str] = None
    cs_press_time: Optional[float] = None
    overlap_start_time: Optional[float] = None  # set only while BOTH keys are held
    overlap_last_start: Optional[float] = None  # most recent finished overlap
    overlap_last_end: Optional[float] = None
    saved_cs: Optional[Tuple[float, float]] = None  # (release, press) of a counter-strafe whose tap has ended
    micro_candidate_duration: Optional[float] = None

    def on_press(self, key: str, timestamp: float) -> None:
        if key in self.held_keys:  # OS key auto-repeat, not a new press
            return
        self.saved_cs = None  # any new key press supersedes an earlier finished tap
        other = self.keys[0] if key == self.keys[1] else self.keys[1]
        self.held_keys.add(key)
        self.press_times[key] = timestamp
        if other in self.held_keys and self.overlap_start_time is None:
            self.overlap_start_time = timestamp
        if self.cs_release_key == other and self.cs_press_time is None:
            self.cs_press_key = key
            self.cs_press_time = timestamp
            self.micro_candidate_duration = None
        self.micro_candidate_duration = None

    def on_release(self, key: str, timestamp: float) -> None:
        press_time = self.press_times.get(key)
        if press_time is not None:
            duration = timestamp - press_time
            if duration < 80:
                self.micro_candidate_duration = duration
        swap_start: Optional[float] = None
        swap_new_key: Optional[str] = None
        if self.overlap_start_time is not None:  # releasing either key ends the overlap
            other_key = self.keys[0] if key == self.keys[1] else self.keys[1]
            if (
                timestamp - self.overlap_start_time < OVERLAP_MIN_MS
                and self.press_times.get(other_key) == self.overlap_start_time
            ):
                # brief overlap where the OLD key was lifted: hall-effect style swap
                swap_start, swap_new_key = self.overlap_start_time, other_key
            else:
                self.overlap_last_start = self.overlap_start_time
                self.overlap_last_end = timestamp
            self.overlap_start_time = None
        if (
            self.cs_press_key == key
            and self.cs_press_time is not None
            and self.cs_release_time is not None
        ):
            # letting go of the counter key ends the tap; the counter-strafe still happened
            self.saved_cs = (self.cs_release_time, self.cs_press_time)
        self.held_keys.discard(key)
        self.cs_release_key = key
        self.cs_release_time = timestamp
        self.cs_press_key = None
        self.cs_press_time = None
        if swap_start is not None:
            # counts as an instant counter-strafe (CS time 0) from the moment the new key went down
            self.cs_release_time = swap_start
            self.cs_press_key = swap_new_key
            self.cs_press_time = swap_start

    def _recent_overlap(self, shot_time: float) -> Optional[Tuple[float, float]]:
        """(start, end) of an overlap that is still happening, or ended just before the shot."""
        if self.overlap_start_time is not None:
            return self.overlap_start_time, shot_time
        if self.overlap_last_end is not None and shot_time - self.overlap_last_end <= OVERLAP_MEMORY_MS:
            return self.overlap_last_start, self.overlap_last_end
        return None

    def _cs_pair(self) -> Optional[Tuple[float, float]]:
        """(release_time, press_time) of the current counter-strafe, if any."""
        if (
            self.cs_press_time is not None
            and self.cs_release_time is not None
            and self.cs_press_time >= self.cs_release_time
        ):
            return self.cs_release_time, self.cs_press_time
        return self.saved_cs

    def classify_shot(self, shot_time: float) -> Tuple[str, Optional[float], Optional[float]]:
        pair = self._cs_pair()
        if (
            pair is None
            and self.overlap_start_time is not None
            and shot_time - self.overlap_start_time < OVERLAP_MIN_MS
        ):
            pair = (self.overlap_start_time, self.overlap_start_time)  # shot fired mid-swap
        window = self._recent_overlap(shot_time)
        if window is not None:
            start, end = window
            overlap_len = end - start
            cleaned_up = pair is not None and pair[0] > start
            if overlap_len >= OVERLAP_MIN_MS and not cleaned_up:
                self._reset(shot_time)
                return "Overlap", overlap_len, None
        if pair is not None:
            cs_time = pair[1] - pair[0]
            shot_delay = shot_time - pair[1]
            self._reset(shot_time)
            return "Counter‑strafe", cs_time, shot_delay
        if self.cs_release_time is not None and self.cs_press_time is None and not self.held_keys:
            released_ago = shot_time - self.cs_release_time
            self._reset(shot_time)
            if released_ago <= SLOW_STOP_MAX:
                return "Slow stop", released_ago, None
            return "Standing", None, None
        standing = not self.held_keys
        self._reset(shot_time)
        return ("Standing" if standing else "Bad"), None, None

    def _reset(self, shot_time: float) -> None:
        self.cs_release_key = None
        self.cs_release_time = None
        self.cs_press_key = None
        self.cs_press_time = None
        self.saved_cs = None
        self.overlap_last_start = None
        self.overlap_last_end = None
        # if both keys are still down after the shot, the overlap carries on from here
        self.overlap_start_time = shot_time if len(self.held_keys) == 2 else None
        self.micro_candidate_duration = None


@dataclass
class ShotClassification:
    label: str  # Perfect, Good, Bad, Overlap, Standing, Crouching (classifier emits raw "Counter‑strafe"/"Slow stop")
    cs_time: Optional[float] = None
    shot_delay: Optional[float] = None
    overlap_time: Optional[float] = None
    release_ago: Optional[float] = None

    TITLES = {
        "Perfect": "Perfect counter-strafe",
        "Good": "Good counter-strafe",
        "Bad": "Bad counter-strafe",
        "Overlap": "Overlap",
        "Standing": "Standing still",
        "Crouching": "Crouching",
    }

    def to_display_string(self) -> str:
        lines = [f"Classification: {self.TITLES.get(self.label, self.label)}"]
        if self.label == "Overlap" and self.overlap_time is not None:
            lines.append(f"Overlap: {self.overlap_time:.0f} ms")
        elif self.release_ago is not None:
            lines.append(f"Released {self.release_ago:.0f} ms before shot")
        elif self.cs_time is not None and self.shot_delay is not None:
            lines.append(f"CS time: {self.cs_time:.0f} ms")
            lines.append(f"Shot delay: {self.shot_delay:.0f} ms")
        return "\n".join(lines)


class MovementClassifier:
    """
    Classifies player movement based on key presses and releases.

    By default the classifier tracks the conventional vertical (forward/backward)
    and horizontal (left/right) movement keys. Custom key bindings can be
    supplied to accommodate different keyboard layouts or player preferences.
    """

    def __init__(self, *, vertical_keys: Tuple[str, str] = ("W", "S"), horizontal_keys: Tuple[str, str] = ("A", "D")) -> None:
        v_keys = tuple(key.upper() for key in vertical_keys)
        h_keys = tuple(key.upper() for key in horizontal_keys)
        if len(set(v_keys)) != 2:
            raise ValueError(f"vertical_keys must contain two distinct keys, got {vertical_keys}")
        if len(set(h_keys)) != 2:
            raise ValueError(f"horizontal_keys must contain two distinct keys, got {horizontal_keys}")
        self.vertical = AxisState(keys=v_keys)
        self.horizontal = AxisState(keys=h_keys)

    def on_press(self, key: str, timestamp: float) -> None:
        if key in self.vertical.keys:
            self.vertical.on_press(key, timestamp)
        elif key in self.horizontal.keys:
            self.horizontal.on_press(key, timestamp)

    def on_release(self, key: str, timestamp: float) -> None:
        if key in self.vertical.keys:
            self.vertical.on_release(key, timestamp)
        elif key in self.horizontal.keys:
            self.horizontal.on_release(key, timestamp)

    def classify_shot(self, shot_time: float) -> ShotClassification:
        v_label, v_val1, v_val2 = self.vertical.classify_shot(shot_time)
        h_label, h_val1, h_val2 = self.horizontal.classify_shot(shot_time)
        negativity = {
            "Overlap": 3,
            "Counter‑strafe": 2,
            "Slow stop": 1,
            "Bad": 0,
            "Standing": -1,
        }
        v_score = negativity.get(v_label, 0)
        h_score = negativity.get(h_label, 0)
        if v_score > h_score:
            label, val1, val2 = v_label, v_val1, v_val2
        elif h_score > v_score:
            label, val1, val2 = h_label, h_val1, h_val2
        else:
            if v_val1 is not None and h_val1 is not None:
                if v_val1 >= h_val1:
                    label, val1, val2 = v_label, v_val1, v_val2
                else:
                    label, val1, val2 = h_label, h_val1, h_val2
            elif v_val1 is not None:
                label, val1, val2 = v_label, v_val1, v_val2
            else:
                label, val1, val2 = h_label, h_val1, h_val2
        if label == "Counter‑strafe":
            return ShotClassification(label=label, cs_time=val1, shot_delay=val2)
        elif label == "Overlap":
            return ShotClassification(label=label, overlap_time=val1)
        elif label == "Slow stop":
            return ShotClassification(label=label, release_ago=val1)
        return ShotClassification(label=label)