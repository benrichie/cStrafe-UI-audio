# cStrafe Audio (fork)

<!-- Demo video (with sound):  -->
https://github.com/user-attachments/assets/7dda5fa9-032e-4c83-b682-00f5dfe5d70e

Fork of [cs2kitchen/cStrafe-UI-minimal](https://github.com/cs2kitchen/cStrafe-UI-minimal), a CS2 counter-strafe trainer. Made for personal use. Changes written with Claude (AI) and lightly tested.

## Installation
https://youtu.be/XWCNudz3QrA?t=413

## Run

```bash
pip install pynput
python main.py        # --debug logs key events
```

CS2 must be borderless windowed to view hud. **F6** hide · **F7** mute · **F8** exit · **=** / **-** size

## Labels

| Label | Sound | Rule |
|---|---|---|
| Perfect | bright arpeggio | ≤ 50 ms release → opposite press, ≤ 110 ms press → shot |
| Good | soft ping | Valid counter-strafe that isn't Perfect |
| Bad | soft low tone | Too slow, or no counter-strafe (including release only) |
| Overlap | double beep | Opposing keys held together ≥ 25 ms |
| Standing still | none | No keys held |
| Crouching | none | Crouch key held |

Thresholds: top of `classifier.py`.

## Changes

- Audio feedback (`audio.py`), F7 mute
- Perfect / Good / Bad tiers (original: Counter-strafe / Overlap / Bad)
- Crouching label, no sound; `CROUCH_KEY` in `movement_keys.py`
- Standing still label, no sound
- Movement keys still read while Ctrl is held (Windows)
- Overlap only counts if ≥ 25 ms and recent (original never expired it until the next shot)
- Hall effect fix: new key pressed just before the old one lifts (< 25 ms) = instant counter-strafe, not Overlap
- Counter-strafe still counts if the counter key is released before the shot
- Overlay shows overlap length and ms since release
- Key auto-repeat ignored
- `--debug` key event log
- Fixed install line, added `.gitignore`

Original by CS2 Kitchen, MIT (see `LICENSE`).
