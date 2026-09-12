#!/usr/bin/env python3
"""
Chart python/galactic_raiders/logs/telemetry.jsonl -- run this on your
laptop after a play session (copy the log off the device, or run
straight off the SD card mount) to get an "aggression over time" demo
slide, plus a couple of other useful views.

Usage:
    python3 tools/plot_telemetry.py [path/to/telemetry.jsonl]

Requires matplotlib (`pip install matplotlib`); this script is
intentionally kept outside python/requirements.txt since it's a
laptop-side dev tool, not something the handheld needs at runtime.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> None:
    default_path = Path(__file__).resolve().parent.parent / "python" / "galactic_raiders" / "logs" / "telemetry.jsonl"
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    if not path.exists():
        print(f"No telemetry log found at {path}")
        print("Play a run first (telemetry logs automatically), or pass a path explicitly.")
        return

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is required: pip install matplotlib")
        return

    rows = load_rows(path)
    samples = [r for r in rows if r.get("event") == "sample" and "aggression" in r]
    if not samples:
        print("No 'sample' rows with an 'aggression' field found in the log yet.")
        return

    t0 = samples[0]["t"]
    times = [r["t"] - t0 for r in samples]
    aggression = [r.get("aggression", 0) for r in samples]
    accuracy = [r.get("accuracy", 0) for r in samples]

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(times, aggression, color="#e04040", label="Aggression")
    ax1.plot(times, accuracy, color="#40a0e0", label="Accuracy")
    ax1.set_xlabel("Seconds into run")
    ax1.set_ylabel("0..1")
    ax1.set_title("Adaptive AI: player signal over time")
    ax1.legend(loc="upper right")
    ax1.grid(alpha=0.25)

    events = [r for r in rows if r.get("event") not in (None, "sample")]
    for e in events[:40]:  # don't clutter the chart on a long log
        ax1.axvline(e["t"] - t0, color="#888", alpha=0.25, linestyle="--")

    out_path = path.parent / "telemetry_chart.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved chart to {out_path}")
    plt.show()


if __name__ == "__main__":
    main()
