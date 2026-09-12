"""
Edge Impulse integration scaffold.

Two swap-in points for a real Edge Impulse model, ties directly to
the sponsor tech track:

  1. EdgeImpulseClassifier -- classify play style from a feature
     vector (aggression / accuracy / reaction time / risk tolerance).
     Train an "Impulse" on a numeric/tabular dataset in Edge Impulse
     Studio if you want this to be a real learned model instead of the
     rule-based stub below.

  2. ShoutGestureDetector -- gesture/shout recognition from the
     MAX9814 mic envelope. Train an audio-classification Impulse
     ("shout" vs "quiet"/background) if you want smarter detection
     than the raw envelope-threshold stub used today.

Neither requires Edge Impulse to demo: both backends default to a
small rule-based/threshold "stub" implementation with the exact same
interface, so the game runs identically with or without a trained
model plugged in. Flip EI_BACKEND=eim (env var) once a real model is
wired up in _load_real_model() below.

To wire up a real model:
  1. Train + export the Impulse from edgeimpulse.com.
  2. Export as a "Linux (Python)" library, e.g.:
         pip install <exported-package>.whl
     or download the .eim binary and use the edge_impulse_linux
     runner (`pip install edge_impulse_linux`).
  3. Fill in _load_real_model() and _classify_real() / _detect_real()
     below with the exported API's actual calls.
  4. Run with EI_BACKEND=eim python3 main.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Sequence

BACKEND = os.environ.get("EI_BACKEND", "stub")  # "stub" or "eim"


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    raw_scores: dict = field(default_factory=dict)


class EdgeImpulseClassifier:
    """Feature-vector play-style classifier.

    Feature vector order (see PlayerProfile.feature_vector() in
    adaptive_ai.py, which is the intended source of these numbers):
        [aggression, accuracy, reaction_time_norm, risk_tolerance]
    all normalized to roughly 0..1.
    """

    LABELS = ("AGGRESSIVE_RUSHER", "CAUTIOUS_SNIPER", "CHAOTIC_BRAWLER", "BALANCED_RAIDER")

    def __init__(self) -> None:
        self._model: Any = None
        if BACKEND == "eim":
            self._model = self._load_real_model()

    def _load_real_model(self) -> Any:
        # TODO: load your exported Edge Impulse runner here, e.g.:
        #     from edge_impulse_linux.runner import ImpulseRunner
        #     runner = ImpulseRunner("playstyle_model.eim")
        #     runner.init()
        #     return runner
        return None

    def classify(self, feature_vector: Sequence[float]) -> ClassificationResult:
        if self._model is not None:
            return self._classify_real(feature_vector)
        return self._classify_stub(feature_vector)

    def _classify_real(self, feature_vector: Sequence[float]) -> ClassificationResult:
        # TODO: e.g.
        #     res = self._model.classify(list(feature_vector))
        #     scores = res["result"]["classification"]
        #     label = max(scores, key=scores.get)
        #     return ClassificationResult(label, scores[label], scores)
        raise NotImplementedError("Wire up your exported model in _load_real_model()/_classify_real().")

    def _classify_stub(self, feature_vector: Sequence[float]) -> ClassificationResult:
        values = list(feature_vector) + [0.0, 0.0, 0.0, 0.0]
        aggression, accuracy, reaction_norm, risk = values[:4]
        scores = {
            "AGGRESSIVE_RUSHER": max(0.0, aggression * 0.6 + risk * 0.4),
            "CAUTIOUS_SNIPER": max(0.0, accuracy * 0.7 + (1 - aggression) * 0.3),
            "CHAOTIC_BRAWLER": max(0.0, risk * 0.5 + (1 - accuracy) * 0.5),
            "BALANCED_RAIDER": max(0.0, 1 - abs(aggression - 0.5) * 2),
        }
        label = max(scores, key=scores.get)
        total = sum(scores.values()) or 1.0
        return ClassificationResult(label=label, confidence=scores[label] / total, raw_scores=scores)


class ShoutGestureDetector:
    """Gesture/shout recognition scaffold on top of the raw MAX9814
    mic envelope (game.mic_sensor.get_intensity()). Same stub/eim
    backend split as EdgeImpulseClassifier: a real Edge Impulse audio
    model can replace _detect_stub()'s threshold logic without
    changing anything that calls update()."""

    def __init__(self, sustain_threshold: float = 0.72, sustain_seconds: float = 0.35) -> None:
        self.sustain_threshold = sustain_threshold
        self.sustain_seconds = sustain_seconds
        self._above_time = 0.0
        self._fired = False
        self._model: Any = None
        if BACKEND == "eim":
            self._model = self._load_real_model()

    def _load_real_model(self) -> Any:
        # TODO: load an Edge Impulse audio-classification runner here.
        return None

    def update(self, dt: float, mic_intensity: float) -> bool:
        """Feed once per frame with the current 0..1 mic intensity.
        Returns True on the single frame a sustained "shout" is first
        detected (edge-triggered, not level-triggered, so holding a
        shout for 3 seconds only fires once)."""
        if self._model is not None:
            return self._detect_real(dt, mic_intensity)
        return self._detect_stub(dt, mic_intensity)

    def _detect_real(self, dt: float, mic_intensity: float) -> bool:
        # TODO: run the real classifier on a rolling audio buffer and
        # return True on a "SHOUT" classification edge.
        raise NotImplementedError("Wire up your exported audio model in _load_real_model()/_detect_real().")

    def _detect_stub(self, dt: float, mic_intensity: float) -> bool:
        if mic_intensity >= self.sustain_threshold:
            self._above_time += dt
            if self._above_time >= self.sustain_seconds and not self._fired:
                self._fired = True
                return True
        else:
            self._above_time = 0.0
            self._fired = False
        return False
