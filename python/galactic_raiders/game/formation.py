"""
Formation manager: builds each wave's group of enemies for the current
layer, sways them, triggers dives/charges, and (for Layers 1 & 2)
biases the next wave's spawn lanes using the adaptive player profile.
Layer 3 (Beast Among Beasts) deliberately skips the adaptive bias --
its whole identity is chaotic, uncoordinated beasts.
"""

import math
import random

from .constants import (
    WIDTH, HEIGHT, EnemyType, EnemyState, ENEMY_BULLET_SPEED, Layer,
    LAYER_ENEMY_TYPES, FATIGUE_EASE_CAP, STEALTH_LIGHT_THRESHOLD,
    STEALTH_DIVE_SUPPRESSION,
)
from .enemy import Enemy
from .adaptive_ai import ChaosDirector


class Formation:
    def __init__(self, layer, wave, player_profile=None, fatigue_level=0.0, chaos_director=None):
        self.layer = layer
        self.wave = wave  # 1..10
        self.enemies = []
        self.time = 0.0
        self.sway_amplitude = 55
        self.sway_freq = 0.5
        self.player_profile = player_profile
        # 0..1, mirrored each frame from game.fatigue_level (A2
        # photoresistor). Read once at wave-build time, same as the
        # player_profile-driven biases above/below.
        self.fatigue_level = fatigue_level

        # Layer III runs a ChaosDirector instead of the adaptive
        # profile -- see adaptive_ai.py. Reused across waves within a
        # layer run (passed in by game.py) so its own timer doesn't
        # reset every wave.
        self.chaos = chaos_director if layer == Layer.BEAST_AMONG_BEASTS else None
        self._chaos_speed_mult = 1.0  # bumped during a FRENZY chaos event

        params = self._wave_params(wave)
        self.dive_cooldown_range = params["dive_cooldown_range"]
        self.dive_duration = params["dive_duration"]
        self.dive_bullet_speed = params["dive_bullet_speed"]
        self.max_simultaneous_divers = params["max_divers"]

        self._build_grid()

    def _wave_params(self, wave):
        dive_mult = 1.0
        if self.layer != Layer.BEAST_AMONG_BEASTS and self.player_profile:
            dive_mult = self.player_profile.suggested_dive_rate_multiplier()
            # Performance-based auto-scaling: nudge difficulty from how
            # the player is actually doing (accuracy), not just which
            # wave number this is -- a sharpshooter gets pushed harder
            # than the static wave curve alone would push them.
            dive_mult *= self._performance_factor()

        # Fatigue easing: a dimmer room softens WAVE difficulty only,
        # capped, and left out of boss fights (BossLearner.scale()) on
        # purpose -- those stay a fixed challenge regardless of fatigue.
        # matches FATIGUE_EASE_CAP_PCT in main.py
        fatigue = max(0.0, min(1.0, getattr(self, "fatigue_level", 0.0)))
        ease = fatigue * FATIGUE_EASE_CAP
        dive_mult *= max(0.1, 1.0 - ease)  # slower dives = easier, same direction as dive_mult

        # Stealth: a notably dim room (beyond plain fatigue easing)
        # also suppresses how eagerly enemies dive at all, flavored as
        # "they can't see you as well" rather than just "it's easier".
        if fatigue >= STEALTH_LIGHT_THRESHOLD:
            dive_mult *= max(0.1, 1.0 - STEALTH_DIVE_SUPPRESSION)

        return {
            "dive_cooldown_range": (max(0.5, 2.4 - wave * 0.13) / dive_mult,
                                     max(1.2, 4.2 - wave * 0.18) / dive_mult),
            "dive_duration": max(1.6, 3.0 - wave * 0.08),
            "dive_bullet_speed": min(460, ENEMY_BULLET_SPEED + wave * 12),
            "max_divers": min(5, 1 + wave // 2),
        }

    def _performance_factor(self):
        """0.7x .. 1.3x multiplier derived from the player's actual
        landed-hit accuracy this run, so difficulty auto-scales with
        how well they're really doing rather than a fixed wave curve."""
        if not self.player_profile:
            return 1.0
        accuracy = self.player_profile.accuracy()  # 0..1, 0.5 neutral
        return max(0.7, min(1.3, 0.7 + accuracy * 1.2))

    def is_stealth_active(self):
        return self.fatigue_level >= STEALTH_LIGHT_THRESHOLD

    def _build_grid(self):
        types = LAYER_ENEMY_TYPES[self.layer]
        # more enemies & more of the tougher variant as waves progress
        base_count = 6 + self.wave  # wave 1 -> 7, wave 10 -> 16
        tough_ratio = min(0.6, 0.1 + self.wave * 0.05)

        # adaptive weapon counter (layers 1 & 2 only): leaning on the
        # Infinity Ray (hits every enemy in a row) means more tough
        # enemies survive a sweep; leaning on a single-target weapon
        # means fewer, so spamming it pays off less.
        if self.layer != Layer.BEAST_AMONG_BEASTS and self.player_profile:
            favorite = self.player_profile.favorite_weapon()
            if favorite == "X":
                tough_ratio = min(0.75, tough_ratio + 0.2)
            else:
                tough_ratio = max(0.05, tough_ratio - 0.1)
            tough_ratio = max(0.05, min(0.85, tough_ratio * self._performance_factor()))

        # Fatigue easing, same reasoning as dive_mult above: nudges the
        # tough-enemy ratio down a bit in dim rooms, waves only.
        if self.layer != Layer.BEAST_AMONG_BEASTS:
            fatigue = max(0.0, min(1.0, self.fatigue_level))
            tough_ratio = max(0.05, tough_ratio * (1.0 - fatigue * 0.35))

        rows = 4
        cols = max(2, base_count // rows + 1)
        row_gap = 46
        col_gap = 44
        right_margin = 70
        top_margin = 60

        # adaptive lane bias (layers 1 & 2 only)
        bias_row = None
        if self.layer != Layer.BEAST_AMONG_BEASTS and self.player_profile:
            bias_row = self.player_profile.bias_spawn_lane(rows)

        delay = 0.0
        count_built = 0
        for row_idx in range(rows):
            row_cols = cols
            if bias_row is not None and row_idx == bias_row:
                row_cols += 2  # stack extra enemies into the player's favorite lane
            slot_y = top_margin + row_idx * ((HEIGHT - 2 * top_margin) / max(1, rows - 1)) if rows > 1 else HEIGHT / 2
            side = "top" if row_idx % 2 == 0 else "bottom"
            for col in range(row_cols):
                if count_built >= base_count + (2 if bias_row is not None else 0):
                    break
                slot_x = WIDTH - right_margin - col * col_gap
                is_tough = random.random() < tough_ratio
                etype = types[1] if (is_tough and len(types) > 1) else types[0]
                enemy = Enemy(etype, slot_x, slot_y, side, delay)
                self.enemies.append(enemy)
                delay += random.uniform(0.05, 0.12)
                count_built += 1

    def alive_enemies(self):
        return [e for e in self.enemies if e.alive]

    def cleared(self):
        return len(self.alive_enemies()) == 0

    def all_entered(self):
        return all(e.state != EnemyState.ENTERING for e in self.alive_enemies()) if self.alive_enemies() else True

    def update(self, dt, player, bullets, particles, sounds):
        self.time += dt
        formation_dy = math.sin(self.time * self.sway_freq * math.tau / 4) * self.sway_amplitude

        chaos_event = None
        if self.chaos is not None:
            chaos_event = self.chaos.update(dt)
            self._chaos_speed_mult = 1.6 if self.chaos.is_active("FRENZY") else 1.0

        alive = self.alive_enemies()
        divers = [e for e in alive if e.state == EnemyState.DIVING]
        ready = [e for e in alive if e.state == EnemyState.FORMATION and not e.erratic]

        max_divers = self.max_simultaneous_divers
        if self.chaos is not None and self.chaos.is_active("PACK_RUSH"):
            max_divers += 3  # scripted chaos burst: several beasts rush at once

        if self.all_entered() and len(divers) < max_divers and ready:
            dive_chance = dt * 0.6
            if self.chaos is not None and self.chaos.is_active("PACK_RUSH"):
                dive_chance *= 4.0
            if random.random() < dive_chance:
                candidate = random.choice(ready)
                candidate.start_dive(player.x, player.y, self.dive_duration,
                                      player_vx=getattr(player, "vx", 0.0),
                                      player_vy=getattr(player, "vy", 0.0))

        for e in alive:
            e.update(dt, formation_dy, player, bullets, sounds, self.dive_bullet_speed,
                      other_enemies=alive, speed_mult=self._chaos_speed_mult)

        if self.chaos is not None and self.chaos.is_active("MUTATION") and alive:
            # pick (and remember) one beast to visibly buff for the
            # duration of the event; harmless if it's already dead by
            # the time the event ends, next MUTATION picks a new one.
            if getattr(self, "_mutated_enemy", None) not in alive:
                target = random.choice(alive)
                if not getattr(target, "_mutated", False):
                    target._mutated = True
                    target.hp = int(target.hp * 1.6)
                    target.max_hp = int(target.max_hp * 1.6)
                    target.size = int(target.size * 1.25)
                self._mutated_enemy = target

        if self.layer == Layer.BEAST_AMONG_BEASTS:
            self._resolve_beast_friendly_fire(alive)

        return chaos_event  # game.py turns a non-None event into an AI/chaos toast

    def _resolve_beast_friendly_fire(self, alive):
        """Uncoordinated beasts occasionally bump into and hurt each
        other when they drift too close."""
        for i, a in enumerate(alive):
            if a.state != EnemyState.FORMATION:
                continue
            for b in alive[i + 1:]:
                if b.state != EnemyState.FORMATION:
                    continue
                dx, dy = a.x - b.x, a.y - b.y
                dist_sq = dx * dx + dy * dy
                min_dist = (a.size + b.size) * 0.45
                if dist_sq < min_dist * min_dist and random.random() < 0.02:
                    a.hp -= 1
                    b.hp -= 1
                    if a.hp <= 0:
                        a.alive = False
                    if b.hp <= 0:
                        b.alive = False

    def draw(self, surface):
        for e in self.alive_enemies():
            e.draw(surface)
