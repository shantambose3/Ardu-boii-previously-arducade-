"""
Local save file: player profiles, the top-5 leaderboard, and a couple
of misc settings (secret unlock, OLED-stats-hidden preference),
persisted to a JSON file so the game "remembers" the player between
boots -- not just within a single run.

Deliberately plain JSON rather than SQLite: the save data is small,
read/written wholesale a handful of times per session, and JSON is
trivially human-inspectable during a demo ("here's the save file").
Writes are atomic (write to a temp file, then os.replace()) so a power
cut mid-save on an SD card can't corrupt the file, and every public
function fails soft (logs to stderr, returns a safe default) instead
of crashing the game over a filesystem hiccup.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))          # .../game
_PKG_DIR = os.path.dirname(_THIS_DIR)                             # .../galactic_raiders

# Override with ARDU_CADE_SAVE_DIR if you want the save file somewhere
# else on the real device (e.g. a persistent partition).
SAVE_DIR = os.environ.get("ARDU_CADE_SAVE_DIR", os.path.join(_PKG_DIR, "save"))
SAVE_PATH = os.path.join(SAVE_DIR, "player_save.json")

SAVE_FORMAT_VERSION = 1


def _default_save() -> dict:
    return {
        "version": SAVE_FORMAT_VERSION,
        "profiles": {},       # layer name -> PlayerProfile.to_dict()
        "leaderboard": [],    # list of {"initials", "score", "layer", "timestamp"}
        "high_score": 0,
        "secret_found": False,
        "oled_stats_hidden": False,
        "total_runs": 0,
    }


def load_save() -> dict:
    """Load the save file, or a fresh default dict if it doesn't exist
    or fails to parse. Never raises."""
    try:
        with open(SAVE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_save()
        merged = _default_save()
        merged.update(data)
        return merged
    except FileNotFoundError:
        return _default_save()
    except (OSError, ValueError) as exc:
        print(f"[persistence] failed to load save file, starting fresh: {exc}", file=sys.stderr)
        return _default_save()


def save_all(data: dict) -> bool:
    """Atomically write `data` to the save file. Returns True on
    success, False (after logging) on any failure -- callers should
    treat a False return as non-fatal."""
    try:
        os.makedirs(SAVE_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".player_save_", dir=SAVE_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, SAVE_PATH)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return True
    except OSError as exc:
        print(f"[persistence] failed to save: {exc}", file=sys.stderr)
        return False


def submit_leaderboard_score(leaderboard: list[dict], initials: str, score: int,
                              layer_name: str, size: int = 5) -> list[dict]:
    """Insert a new score into `leaderboard`, keep it sorted
    descending, and truncate to `size` entries. Pure function -- does
    not touch disk; caller is responsible for persisting the result."""
    import time
    entry = {
        "initials": initials[:3].upper().ljust(3, "-"),
        "score": int(score),
        "layer": layer_name,
        "timestamp": time.time(),
    }
    updated = leaderboard + [entry]
    updated.sort(key=lambda e: e.get("score", 0), reverse=True)
    return updated[:size]


def qualifies_for_leaderboard(leaderboard: list[dict], score: int, size: int = 5) -> bool:
    if score <= 0:
        return False
    if len(leaderboard) < size:
        return True
    return score > min(e.get("score", 0) for e in leaderboard)
