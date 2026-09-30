import re
import sys
import threading
import time
from typing import Optional

from pynput import keyboard, mouse

from audio import AudioFeedback
from classifier import (
    MAX_SHOT_DELAY,
    MAX_SLOW_BOTH,
    PERFECT_CS_MAX,
    PERFECT_DELAY_MAX,
    MovementClassifier,
    ShotClassification,
)

try:
    # Attempt to import user configured keys. The movement_keys module defines
    # FORWARD, BACKWARD, LEFT and RIGHT constants. If it cannot be imported or
    # does not define the expected attributes, defaults will be used later.
    from movement_keys import FORWARD, BACKWARD, LEFT, RIGHT  # type: ignore
except Exception:
    # Provide dummy values here; real defaults are set below in InputListener
    FORWARD = 'E'  # type: ignore
    BACKWARD = 'D'  # type: ignore
    LEFT = 'S'  # type: ignore
    RIGHT = 'F'  # type: ignore

try:
    from movement_keys import SHOOT_BUTTON  # type: ignore
except Exception:
    SHOOT_BUTTON = 'left'  # type: ignore

try:
    from movement_keys import CROUCH_KEY  # type: ignore
except Exception:
    CROUCH_KEY = 'ctrl'  # type: ignore

DEBUG = "--debug" in sys.argv


class InputListener:
    def __init__(self, overlay: "Overlay") -> None:
        self.overlay = overlay
        self.audio = AudioFeedback()
        self._t0 = time.time() * 1000.0
        # Determine movement keys from configuration. Use uppercase to
        # standardise comparisons. Fallback to defaults if the values are
        # missing or invalid.
        try:
            forward = str(FORWARD)
            backward = str(BACKWARD)
            left = str(LEFT)
            right = str(RIGHT)
        except Exception:
            forward, backward, left, right = 'W', 'S', 'A', 'D'
        # Ensure single characters and normalise to uppercase
        forward = (forward[0] if forward else 'W').upper()
        backward = (backward[0] if backward else 'S').upper()
        left = (left[0] if left else 'A').upper()
        right = (right[0] if right else 'D').upper()
        self._movement_keys = {forward, backward, left, right}
        self._shoot_button = self._parse_shoot_button(SHOOT_BUTTON)
        self._crouch_keys, self._crouch_base, self._crouch_chars = self._parse_crouch_key(CROUCH_KEY)
        self._crouch_held = False

        # Initialise classifier with the configured key pairs
        try:
            self.classifier = MovementClassifier(vertical_keys=(forward, backward), horizontal_keys=(left, right))
        except Exception:
            # Fallback to default WASD if invalid configuration is provided
            self.classifier = MovementClassifier()
        self._lock = threading.Lock()
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None

    def start(self) -> None:
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._keyboard_listener.start()
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
        )
        self._mouse_listener.start()
        
    def _parse_shoot_button(self, value: object) -> mouse.Button:
        button = str(value).strip().lower()

        if button in {'right', 'mouse.right', 'm2', '2'}:
            return mouse.Button.right

        if button in {'middle', 'mouse.middle', 'm3', '3'}:
            return mouse.Button.middle

        return mouse.Button.left

    _KEY_ALIASES = {
        "control": "ctrl", "lctrl": "ctrl_l", "rctrl": "ctrl_r",
        "left_ctrl": "ctrl_l", "right_ctrl": "ctrl_r",
        "lshift": "shift_l", "rshift": "shift_r",
        "left_shift": "shift_l", "right_shift": "shift_r",
        "lalt": "alt_l", "ralt": "alt_r", "left_alt": "alt_l", "right_alt": "alt_r",
        "capslock": "caps_lock", "caps": "caps_lock",
    }

    @classmethod
    def _parse_crouch_key(cls, value: object):
        """Return (Key set, base name or None, single-character set).

        A bare name like "shift" matches left and right variants; "shift_l" /
        "lshift" matches only the left one. Single characters match that key.
        """
        raw = str(value).strip()
        if len(raw) == 1:
            return set(), None, {raw.lower()}
        name = re.sub(r"[\s\-]+", "_", raw.lower())
        name = cls._KEY_ALIASES.get(name, name)
        special = getattr(keyboard.Key, name, None)
        if special is None:
            print(f"[cStrafe] Unknown CROUCH_KEY {value!r}; falling back to 'ctrl'", flush=True)
            name, special = "ctrl", keyboard.Key.ctrl
        keys = {special}
        base = None
        if not name.endswith(("_l", "_r")):
            base = name
            for suffix in ("_l", "_r"):
                variant = getattr(keyboard.Key, name + suffix, None)
                if variant is not None:
                    keys.add(variant)
        return keys, base, set()

    @staticmethod
    def _key_char(key) -> Optional[str]:
        """Return the character for a key, or None.

        On Windows pynput reports letters as control characters while Ctrl is
        held (e.g. Ctrl+W -> '\\x17'), which would hide movement keys while
        crouching. Fall back to the virtual-key code for A-Z in that case.
        """
        char = getattr(key, "char", None)
        if char and char.isprintable():
            return char
        if sys.platform == "win32":
            vk = getattr(key, "vk", None)
            if vk is not None and 65 <= vk <= 90:
                return chr(vk)
        return None

    def _is_crouch_key(self, key) -> bool:
        if key in self._crouch_keys:
            return True
        if self._crouch_base:
            name = getattr(key, "name", None)
            if name and re.sub(r"_(l|r)$", "", name) == self._crouch_base:
                return True
        char = getattr(key, "char", None)
        return bool(char) and char.lower() in self._crouch_chars

    def _debug(self, kind: str, detail: object) -> None:
        if DEBUG:
            print(f"[{time.time() * 1000.0 - self._t0:10.1f} ms] {kind:5s} {detail!r}", flush=True)

    def _on_key_press(self, key: keyboard.Key) -> None:
        self._debug("down", key)
        if key == keyboard.Key.f6:
            self.overlay.toggle_visibility()
            return
        if key == keyboard.Key.f7:
            self.audio.toggle()
            return
        if key == keyboard.Key.f8:
            self.stop()
            self.audio.cleanup()
            self.overlay.terminate()
            return
        char_key: Optional[str] = None
        try:
            char_key = key.char
        except AttributeError:
            char_key = None
        if char_key == "=":
            self.overlay.increase_size()
            return
        if char_key == "-":
            self.overlay.decrease_size()
            return
        timestamp = time.time() * 1000.0
        if self._is_crouch_key(key):
            if not self._crouch_held:
                self._debug("crouch", "on")
            self._crouch_held = True
            return
        char = self._key_char(key)
        if char:
            upper_char = char.upper()
            if upper_char in self._movement_keys:
                with self._lock:
                    self.classifier.on_press(upper_char, timestamp)

    def _on_key_release(self, key: keyboard.Key) -> None:
        self._debug("up", key)
        timestamp = time.time() * 1000.0
        if self._is_crouch_key(key):
            self._debug("crouch", "off")
            self._crouch_held = False
            return
        char = self._key_char(key)
        if char:
            upper_char = char.upper()
            if upper_char in self._movement_keys:
                with self._lock:
                    self.classifier.on_release(upper_char, timestamp)

    def _on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        if button != self._shoot_button:
            return

        if not pressed:
            return

        current_time = time.time() * 1000.0

        with self._lock:
            base_result = self.classifier.classify_shot(current_time)  # also resets state

        if self._crouch_held:
            final_result = ShotClassification(label="Crouching")
        else:
            final_result = self._build_classification(base_result, current_time)
        self.audio.play(final_result.label)
        self._debug("SHOT", final_result.to_display_string().replace("\n", " | "))
        self.overlay.update_result(final_result)

    def stop(self) -> None:
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
            self._keyboard_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None

    def _build_classification(self, base: ShotClassification, shot_time: float) -> ShotClassification:
        if base.label in ("Overlap", "Standing"):
            return base
        if base.label == "Slow stop":  # released a key but never pressed the opposite one
            return ShotClassification(label="Bad", release_ago=base.release_ago)
        if base.label == "Counter‑strafe" and base.cs_time is not None and base.shot_delay is not None:
            cs, delay = base.cs_time, base.shot_delay
            if delay > MAX_SHOT_DELAY or (cs > MAX_SLOW_BOTH and delay > MAX_SLOW_BOTH):
                label = "Bad"
            elif cs <= PERFECT_CS_MAX and delay <= PERFECT_DELAY_MAX:
                label = "Perfect"
            else:
                label = "Good"
            return ShotClassification(label=label, cs_time=cs, shot_delay=delay)
        return ShotClassification(label="Bad")
