"""
Adaptive AI.

A small local statistical model that watches the player across a
wave/fight -- movement histogram, weapon usage, accuracy, reaction
time, and risk tolerance -- and nudges enemy behavior toward
countering whatever the player leans on. PlayerProfile now persists
across sessions (see game/persistence.py): it's loaded at boot and
saved after each wave/boss/quit, so the game keeps "remembering" the
player across boots, not just within one run.

Used for wave formation/spawn bias on Layers 1 & 2 -- Layer 3 (Beast
Among Beasts) is not adaptive, since its identity is uncoordinated
chaos; it runs ChaosDirector instead (see bottom of this file), a
*scripted* -- not learned -- source of unpredictability. Bosses on all
layers use their own smaller tracker (BossLearner) to progressively
get harder and, now, to taunt the player when its counter-strategy
shifts.
"""
from __future__ import annotations

import random
from typing import Any, Optional


class PlayerProfile:
    """Tracks player habits, both within the current run and (via
    to_dict/from_dict) across the player's whole save file."""

    def __init__(self) -> None:
        # Vertical position histogram
        self.position_buckets = [1, 1, 1, 1, 1]
        # Weapon usage counts (landed hits -- see game.py's _register_weapon_hit)
        self.weapon_usage = {"A": 1, "B": 1, "X": 1, "Y": 1}
        # Aggression: how often player is close to the front line, blended
        # in game.py with real motion/mic sensor signal when available.
        self.aggression_samples: list[float] = []
        self.samples = 0

        # --- multi-axis learning additions ---
        self.shots_fired = {"A": 0, "B": 0, "X": 0, "Y": 0}
        self.shots_hit = {"A": 0, "B": 0, "X": 0, "Y": 0}
        self.reaction_time_samples: list[float] = []  # seconds, lower = faster
        self.risk_samples: list[float] = []            # 0/1, "was this action taken at low health"

        # --- per-run weapon kill tally (see MidRunVerdict below) ---
        # Deliberately NOT persisted across sessions/layers -- this is
        # reset at the start of every layer run (see Game.choose_layer)
        # since the wave-5 verdict judges *this run*, not the player's
        # whole history the way favorite_weapon()/accuracy() do.
        self.weapon_kills = {"A": 0, "B": 0, "X": 0, "Y": 0}

    def record_kill(self, slot_letter: str) -> None:
        """Call once per confirmed kill, with the weapon slot that
        landed the killing blow. Feeds MidRunVerdict.deadliest_weapon()."""
        if slot_letter in self.weapon_kills:
            self.weapon_kills[slot_letter] += 1

    def reset_run_tallies(self) -> None:
        """Called at the start of each layer run -- clears just the
        per-run kill tally, leaving the long-lived learned stats
        (position/weapon-usage/accuracy/etc, which persist to disk)
        untouched."""
        self.weapon_kills = {"A": 0, "B": 0, "X": 0, "Y": 0}

    def deadliest_weapon(self) -> Optional[str]:
        """The weapon with the most kills THIS run, or None if nothing
        has died yet (avoids punishing a weapon that's tied at zero)."""
        if not any(self.weapon_kills.values()):
            return None
        return max(self.weapon_kills, key=self.weapon_kills.get)

    # --- observation hooks (called from game.py) ---
    def observe_position(self, y: float, world_height: float) -> None:
        bucket = min(4, int((y / max(1, world_height)) * 5))
        self.position_buckets[bucket] += 1
        self.samples += 1

    def observe_weapon(self, slot_letter: str) -> None:
        if slot_letter in self.weapon_usage:
            self.weapon_usage[slot_letter] += 1

    def observe_aggression(self, value: float) -> None:
        self.aggression_samples.append(value)
        if len(self.aggression_samples) > 200:
            self.aggression_samples.pop(0)

    def observe_shot_fired(self, slot_letter: str) -> None:
        if slot_letter in self.shots_fired:
            self.shots_fired[slot_letter] += 1

    def observe_shot_hit(self, slot_letter: str) -> None:
        if slot_letter in self.shots_hit:
            self.shots_hit[slot_letter] += 1

    def observe_reaction_time(self, seconds: float) -> None:
        self.reaction_time_samples.append(max(0.0, seconds))
        if len(self.reaction_time_samples) > 100:
            self.reaction_time_samples.pop(0)

    def observe_risk_sample(self, value: float) -> None:
        self.risk_samples.append(max(0.0, min(1.0, value)))
        if len(self.risk_samples) > 200:
            self.risk_samples.pop(0)

    # --- derived stats ---
    def favorite_bucket(self) -> int:
        total = sum(self.position_buckets)
        weights = [c / total for c in self.position_buckets]
        return weights.index(max(weights))

    def favorite_weapon(self) -> str:
        return max(self.weapon_usage, key=self.weapon_usage.get)

    def avg_aggression(self) -> float:
        if not self.aggression_samples:
            return 0.5
        return sum(self.aggression_samples) / len(self.aggression_samples)

    def accuracy(self) -> float:
        """Overall hit-rate across all weapons, 0..1. Returns 0.5
        (neutral) until there's meaningful sample size."""
        fired = sum(self.shots_fired.values())
        if fired < 5:
            return 0.5
        hit = sum(self.shots_hit.values())
        return max(0.0, min(1.0, hit / fired))

    def avg_reaction_time(self) -> float:
        """Average seconds between an incoming threat and the player
        reacting to it. Returns 0.6s (a neutral placeholder) until
        there's data."""
        if not self.reaction_time_samples:
            return 0.6
        return sum(self.reaction_time_samples) / len(self.reaction_time_samples)

    def reaction_time_norm(self) -> float:
        """0..1, higher = faster reactions (inverted + clamped so it's
        directly usable as a feature alongside the other 0..1 axes)."""
        rt = self.avg_reaction_time()
        # 0.15s -> ~1.0 (very fast), 1.2s -> ~0.0 (slow)
        return max(0.0, min(1.0, 1.0 - (rt - 0.15) / 1.05))

    def risk_tolerance(self) -> float:
        """0..1: how often the player keeps engaging (landing hits)
        while at low health. Returns 0.3 (mildly risk-averse default)
        until there's data."""
        if not self.risk_samples:
            return 0.3
        return sum(self.risk_samples) / len(self.risk_samples)

    def feature_vector(self) -> list[float]:
        """[aggression, accuracy, reaction_time_norm, risk_tolerance] --
        the input to EdgeImpulseClassifier.classify() in edge_impulse.py."""
        return [self.avg_aggression(), self.accuracy(), self.reaction_time_norm(), self.risk_tolerance()]

    def bias_spawn_lane(self, num_lanes: int) -> int:
        """Return a lane index the formation should weight extra
        enemies toward, based on where the player likes to sit."""
        bucket = self.favorite_bucket()
        lane = int(bucket / 5 * num_lanes)
        return min(num_lanes - 1, max(0, lane))

    def suggested_dive_rate_multiplier(self) -> float:
        """More aggressive players (staying near the front) get dived
        on more often; passive/back-line players get baited forward."""
        agg = self.avg_aggression()
        return 0.75 + agg * 0.9  # 0.75x .. 1.65x

    # --- persistence ---
    def to_dict(self) -> dict:
        return {
            "position_buckets": list(self.position_buckets),
            "weapon_usage": dict(self.weapon_usage),
            "samples": self.samples,
            "avg_aggression": self.avg_aggression(),
            "shots_fired": dict(self.shots_fired),
            "shots_hit": dict(self.shots_hit),
            "avg_reaction_time": self.avg_reaction_time(),
            "risk_tolerance": self.risk_tolerance(),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "PlayerProfile":
        profile = cls()
        if not isinstance(data, dict):
            return profile
        try:
            return cls._from_dict_unsafe(profile, data)
        except (TypeError, ValueError):
            return cls()  # malformed save data -- start fresh rather than crash

    @classmethod
    def _from_dict_unsafe(cls, profile: "PlayerProfile", data: dict) -> "PlayerProfile":
        profile.position_buckets = list(data.get("position_buckets", profile.position_buckets))[:5] or profile.position_buckets
        for k, v in (data.get("weapon_usage") or {}).items() if isinstance(data.get("weapon_usage"), dict) else []:
            if k in profile.weapon_usage:
                profile.weapon_usage[k] = int(v)
        profile.samples = int(data.get("samples", 0))
        avg_agg = data.get("avg_aggression")
        if isinstance(avg_agg, (int, float)):
            # seed the rolling window with the saved average so new
            # samples blend in smoothly instead of starting neutral
            profile.aggression_samples = [float(avg_agg)] * 10
        for k, v in (data.get("shots_fired") or {}).items() if isinstance(data.get("shots_fired"), dict) else []:
            if k in profile.shots_fired:
                profile.shots_fired[k] = int(v)
        for k, v in (data.get("shots_hit") or {}).items() if isinstance(data.get("shots_hit"), dict) else []:
            if k in profile.shots_hit:
                profile.shots_hit[k] = int(v)
        avg_rt = data.get("avg_reaction_time")
        if isinstance(avg_rt, (int, float)):
            profile.reaction_time_samples = [float(avg_rt)] * 5
        risk = data.get("risk_tolerance")
        if isinstance(risk, (int, float)):
            profile.risk_samples = [float(risk)] * 10
        return profile


class BossLearner:
    """Small per-boss tracker: counts which weapon slot damaged the
    boss most, and how often the player dodges up vs down, then leans
    the boss's own attack/evasion choices to counter it over the
    fight. Also exposes taunt_text() so the fight can visibly call out
    when the boss's counter-strategy shifts (see Boss.pending_taunt in
    boss.py) -- one of the "AI adaptation, visible in real time" asks."""

    def __init__(self) -> None:
        self.damage_by_weapon = {"A": 0, "B": 0, "X": 0, "Y": 0}
        self.dodge_up = 0
        self.dodge_down = 0
        self.hits_taken = 0
        self.difficulty_scale = 1.0
        self._last_taunted_weapon: Optional[str] = None

    def observe_damage(self, slot_letter: str, amount: float) -> None:
        if slot_letter in self.damage_by_weapon:
            self.damage_by_weapon[slot_letter] += amount

    def observe_dodge(self, direction: int) -> None:
        if direction < 0:
            self.dodge_up += 1
        else:
            self.dodge_down += 1

    def observe_hit_taken(self) -> None:
        self.hits_taken += 1
        # boss "learns" -- gets harder the more it eats damage cleanly
        self.difficulty_scale = min(2.2, self.difficulty_scale + 0.015)

    def counter_weapon(self) -> str:
        return max(self.damage_by_weapon, key=self.damage_by_weapon.get)

    def preferred_evade_direction(self) -> int:
        """Evade toward the side the player dodges to LESS, so the
        boss drifts into their comfort zone."""
        if self.dodge_up == self.dodge_down:
            return random.choice([-1, 1])
        return 1 if self.dodge_up > self.dodge_down else -1

    def scale(self) -> float:
        return self.difficulty_scale

    def pending_taunt(self, display_name: str, weapon_names: dict) -> Optional[str]:
        """Returns a one-shot taunt string the first time the boss has
        enough data (>=3 hits taken) to have a clear counter target
        and that target has changed since the last taunt -- or None."""
        if self.hits_taken < 3:
            return None
        current = self.counter_weapon()
        if current == self._last_taunted_weapon:
            return None
        self._last_taunted_weapon = current
        weapon_name = weapon_names.get(current, current)
        return f"{display_name} IS COUNTERING YOUR {weapon_name}!"


class MidRunVerdict:
    """Fires once, after Wave 5 of any layer clears: the AI looks back
    at how this run has gone so far and hands down ONE verdict --
    reward the player, or punish them -- rather than always doing
    both. This is deliberately built on stats PlayerProfile already
    tracks (accuracy, combo multiplier) instead of introducing a
    separate scoring system, so the same "the AI is watching you"
    read that drives spawn bias/dive rate/boss counters also drives
    this.

    REWARD (player struggling): +2 extra lives.
    PUNISH (player dominating): the weapon with the most kills THIS
    run gets locked for WEAPON_LOCK_WAVES waves, forcing a change of
    rhythm rather than just "take away the fun toy forever".
    """

    WEAPON_LOCK_WAVES = 2
    # Accuracy + best-combo-seen are blended into one 0..1 "performance"
    # reading; >= this = AI calls it a dominating run and punishes,
    # otherwise it calls it a struggling run and rewards. No dead zone
    # on purpose -- the AI always has a clear read one way or the other,
    # same philosophy as the rest of the adaptive system (it commits to
    # a read rather than hedging).
    PUNISH_THRESHOLD = 0.55
    ACCURACY_WEIGHT = 0.6
    COMBO_WEIGHT = 0.4

    def __init__(self) -> None:
        self.resolved = False  # one-shot per layer run

    def reset(self) -> None:
        self.resolved = False

    def performance_score(self, profile: "PlayerProfile", best_combo_multiplier: float) -> float:
        from .constants import COMBO_MAX_MULTIPLIER
        acc = profile.accuracy()  # 0..1, 0.5 neutral until real data
        combo_norm = max(0.0, min(1.0, (best_combo_multiplier - 1.0) / max(0.01, COMBO_MAX_MULTIPLIER - 1.0)))
        return self.ACCURACY_WEIGHT * acc + self.COMBO_WEIGHT * combo_norm

    def decide(self, profile: "PlayerProfile", best_combo_multiplier: float):
        """Returns ("REWARD", None) or ("PUNISH", weapon_letter) --
        or (None, None) if there's nothing to punish (no kills yet)
        and the call falls back to a reward instead."""
        self.resolved = True
        score = self.performance_score(profile, best_combo_multiplier)
        if score >= self.PUNISH_THRESHOLD:
            target = profile.deadliest_weapon()
            if target is not None:
                return "PUNISH", target
        return "REWARD", None


class ChaosDirector:
    """Layer III's (Beast Among Beasts) own flavor of "intelligence".

    Layer III deliberately does NOT run PlayerProfile/BossLearner --
    its whole identity is uncoordinated chaos, a system that ISN'T
    studying the player. But "not adaptive" doesn't have to mean
    "off": ChaosDirector is a small scripted state machine that fires
    timed, randomized chaos events on its own clock, independent of
    anything the player does, so Layer III still feels alive and
    reactive -- just unpredictable instead of learned.
    """

    EVENTS = ("FRENZY", "MUTATION", "PACK_RUSH")
    EVENT_LABELS = {
        "FRENZY": "BEASTS FRENZIED!",
        "MUTATION": "A BEAST MUTATES!",
        "PACK_RUSH": "PACK RUSH!",
    }

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)
        self.timer = self.rng.uniform(4.0, 8.0)
        self.active_event: Optional[str] = None
        self.event_timer = 0.0

    def update(self, dt: float) -> Optional[str]:
        """Call once per frame. Returns an event name the single frame
        a new chaos event starts (for a toast/sound), else None."""
        if self.active_event:
            self.event_timer -= dt
            if self.event_timer <= 0:
                self.active_event = None
            return None
        self.timer -= dt
        if self.timer <= 0:
            self.active_event = self.rng.choice(self.EVENTS)
            self.event_timer = self.rng.uniform(2.5, 4.5)
            self.timer = self.rng.uniform(6.0, 11.0)
            return self.active_event
        return None

    def is_active(self, name: str) -> bool:
        return self.active_event == name

    def label_for(self, name: str) -> str:
        return self.EVENT_LABELS.get(name, name)
