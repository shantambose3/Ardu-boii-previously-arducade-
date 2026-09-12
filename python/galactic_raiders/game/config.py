"""
Central config loader for tunable AI/game parameters.

Design goal: let a designer (or a judge poking around before the demo)
retune weapon damage, adaptive-AI weights, sensor thresholds, combo
scoring, etc. by editing one file, instead of hunting through
constants.py.

Lookup order, first one found wins:
  1. config/game_config.yaml   (only if PyYAML is installed)
  2. config/game_config.json   (always available, no extra dependency)
  3. hardcoded defaults already in constants.py (nothing found / key missing)

get(path, default) reads a dotted path like "weapons.nails_damage" out
of the loaded file. constants.py calls this once per tunable value
right after it defines the hardcoded default, so a missing file/key
is always a silent no-op fallback -- the game never fails to start
because of a config problem.
"""
from __future__ import annotations

import json
import os
from typing import Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))          # .../game
_PKG_DIR = os.path.dirname(_THIS_DIR)                            # .../galactic_raiders
_CONFIG_DIR = os.path.join(_PKG_DIR, "config")
_YAML_PATH = os.path.join(_CONFIG_DIR, "game_config.yaml")
_JSON_PATH = os.path.join(_CONFIG_DIR, "game_config.json")


def _load_yaml(path: str) -> dict | None:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _load_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _load_config() -> dict:
    data = _load_yaml(_YAML_PATH)
    if data is not None:
        return data
    data = _load_json(_JSON_PATH)
    if data is not None:
        return data
    return {}


CONFIG: dict = _load_config()


def get(dotted_path: str, default: Any = None) -> Any:
    """Read a dotted path (e.g. 'weapons.nails_damage') out of CONFIG,
    returning `default` if the file, the section, or the key is
    missing -- so callers never need their own try/except."""
    node: Any = CONFIG
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node if node is not None else default


def reload() -> dict:
    """Re-read the config file(s) from disk. Not called automatically
    anywhere (constants.py bakes values in at import time), but handy
    from a REPL or a future 'reload config' debug hotkey."""
    global CONFIG
    CONFIG = _load_config()
    return CONFIG
