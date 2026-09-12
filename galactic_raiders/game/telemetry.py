"""
Lightweight telemetry logger.

Appends one JSON object per line (JSONL -- easy to tail, grep, or load
with pandas.read_json(path, lines=True)) to logs/telemetry.jsonl,
sampling a snapshot of the adaptive AI's view of the player a few
times a second. Meant for exactly one demo moment: "here's the data"
-- see tools/plot_telemetry.py for a ready-made aggression-over-time
chart.

Fails soft: if the log directory isn't writable (read-only rootfs,
full SD card, whatever), logging silently becomes a no-op rather than
crashing the game.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))          # .../game
_PKG_DIR = os.path.dirname(_THIS_DIR)                             # .../galactic_raiders
LOG_DIR = os.environ.get("ARDU_CADE_LOG_DIR", os.path.join(_PKG_DIR, "logs"))
LOG_PATH = os.path.join(LOG_DIR, "telemetry.jsonl")


class TelemetryLogger:
    def __init__(self, sample_interval: float = 0.5) -> None:
        self.sample_interval = sample_interval
        self._timer = 0.0
        self._enabled = True
        self._run_id = int(time.time())
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
        except OSError:
            self._enabled = False

    def log_event(self, event: str, **fields: Any) -> None:
        """Log a one-off event immediately (adaptation toasts, boss
        phase changes, deaths, leaderboard entries, etc.), regardless
        of the periodic sample timer."""
        if not self._enabled:
            return
        row = {"t": time.time(), "run_id": self._run_id, "event": event}
        row.update(fields)
        self._write(row)

    def maybe_sample(self, dt: float, **fields: Any) -> None:
        """Call once per frame with the fields worth graphing
        (aggression, wave, layer, etc.) -- writes a 'sample' row at
        most once every `sample_interval` seconds."""
        if not self._enabled:
            return
        self._timer -= dt
        if self._timer > 0:
            return
        self._timer = self.sample_interval
        self.log_event("sample", **fields)

    def _write(self, row: dict) -> None:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            self._enabled = False  # stop trying for the rest of this run
