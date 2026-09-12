"""
Boss fights. Each layer has its own boss with unique mechanics:

  GENERAL_N (Layer 1)      - fast attack ship, evades the Infinity Ray,
                              fires twin laser bolts (laser_gun) instead
                              of ramming the player.
  GUNNER_EYE + MELEE_EYE   - twin eyeball bosses (Layer 2): GUNNER_EYE
    (Layer 2)                hovers back with continuous gunfire and no
                              melee; MELEE_EYE has no ranged attack and
                              relentlessly charges/rams instead. Both
                              regenerate unless killed within a short
                              window of each other. Infinity Ray hits
                              them easily (no evasion).
  SKULL_O_CTHULHU (Layer 3) - durable cosmic-horror boss. Breathes a
                              rapid 3-shot fire volley, deals 2 lives
                              per melee hit when it charges, and can
                              dodge a carelessly-fired Infinity Ray.

All bosses use a BossLearner (see adaptive_ai.py) to get progressively
harder as the fight goes on.
"""

import math
import random

import pygame

from .constants import (
    WIDTH, HEIGHT, EnemyType, ENEMY_STATS, PIXEL_SCALE,
    RED, YELLOW, PURPLE, WHITE, ORANGE, LASER_RED,
    BOSS_PHASE_THRESHOLDS, BOSS_PHASE_SPEED_SCALE, BOSS_PHASE_COLORS,
    WEAPON_DISPLAY_NAMES,
)
from .helpers import clamp
from .bullets import Bullet
from .particles import spawn_explosion
from .pixel_art import draw_sprite, BOSS_ART
from .adaptive_ai import BossLearner

# Boss-intro card text derives from the enum member name; kept here
# too (not just game.py) so taunts can use the same display name.
_BOSS_DISPLAY_NAME_OVERRIDES = {"SKULL_O_CTHULHU": "SKULL O' CTHULHU"}


REGEN_WINDOW = 6.0          # seconds twins have to both die together
REGEN_HEAL_FRACTION = 0.35  # how much hp a surviving twin regens

_BOSS_ART_KEYS = {
    EnemyType.GENERAL_N: "GENERAL_N",
    EnemyType.GUNNER_EYE: "GUNNER_EYE",
    EnemyType.MELEE_EYE: "MELEE_EYE",
    EnemyType.SKULL_O_CTHULHU: "SKULL_O_CTHULHU",
}


class Boss:
    def __init__(self, etype, x, y):
        self.type = etype
        stats = ENEMY_STATS[etype]
        self.max_hp = stats["hp"]
        self.hp = stats["hp"]
        self.color = stats["color"]
        self.size = stats["size"]
        self.score = stats["score"]
        self.x, self.y = x, y
        self.spawn_x, self.spawn_y = x, y
        self.alive = True
        self.downed = False
        self.defeated_at = None  # game-clock tick for twin sync

        self.evasive = stats.get("evasive", False)
        self.regen = stats.get("regen", False)
        self.heavy_melee = stats.get("heavy_melee", False)
        self.dodge_infinity = stats.get("dodge_infinity", False)
        self.gunner = stats.get("gunner", False)
        self.breathes_fire = stats.get("breathes_fire", False)
        self.laser_gun = stats.get("laser_gun", False)

        self.learner = BossLearner()

        # Boss phase system: visibly different behavior/appearance at
        # hp thresholds (BOSS_PHASE_THRESHOLDS). phase is 0-indexed
        # (0 = full health phase, up to len(BOSS_PHASE_THRESHOLDS)).
        self.phase = 0
        self.phase_flash_timer = 0.0   # brief highlight flash on a phase transition
        self.just_changed_phase = False  # one-frame flag game.py consumes for haptics/swarm spawns
        self.pending_taunt = None      # str, one-shot: game.py consumes it into an AI toast

        self.move_phase = random.uniform(0, math.tau)
        self.attack_cooldown = random.uniform(0.8, 1.6)
        self.melee_cooldown = random.uniform(0.6, 1.2) if etype == EnemyType.MELEE_EYE else random.uniform(1.5, 2.5)
        self.charge_telegraph = 0.0
        self.charging = False
        self.charge_target = None
        self.charge_finished_this_frame = False
        self.regen_pending_partner = None

    @property
    def rect(self):
        s = self.size
        return pygame.Rect(int(self.x - s / 2), int(self.y - s / 2), s, s)

    @property
    def display_name(self):
        return _BOSS_DISPLAY_NAME_OVERRIDES.get(self.type.name, self.type.name.replace("_", " "))

    def _refresh_phase(self, particles, sounds):
        """Check hp fraction against BOSS_PHASE_THRESHOLDS and, if a
        new phase has been crossed, bump self.phase, flash, and play a
        sting -- the visible "boss phase" the game-design ask wants."""
        frac = self.hp / self.max_hp if self.max_hp else 0
        new_phase = 0
        for i, threshold in enumerate(BOSS_PHASE_THRESHOLDS):
            if frac <= threshold:
                new_phase = i + 1
        if new_phase != self.phase:
            self.phase = new_phase
            self.phase_flash_timer = 0.5
            self.just_changed_phase = True
            spawn_count = 24 + new_phase * 8
            flash_color = BOSS_PHASE_COLORS[min(new_phase, len(BOSS_PHASE_COLORS) - 1)] or self.color
            spawn_explosion(particles, self.x, self.y, flash_color, count=spawn_count, speed=200)
            sounds.play("boss_phase")

    def phase_speed_scale(self):
        idx = min(self.phase, len(BOSS_PHASE_SPEED_SCALE) - 1)
        return BOSS_PHASE_SPEED_SCALE[idx]

    # update
    def update(self, dt, player, bullets, particles, sounds):
        if self.downed:
            return
        self._refresh_phase(particles, sounds)
        if self.phase_flash_timer > 0:
            self.phase_flash_timer -= dt
        self.charge_finished_this_frame = False
        self.move_phase += dt
        scale = self.learner.scale() * self.phase_speed_scale()

        taunt = self.learner.pending_taunt(self.display_name, WEAPON_DISPLAY_NAMES)
        if taunt:
            self.pending_taunt = taunt

        base_x = WIDTH * 0.78
        target_dy = math.sin(self.move_phase * 0.8) * 140

        if self.evasive:
            # GENERAL_N: fast, erratic vertical juking
            target_dy += math.sin(self.move_phase * 3.2) * 60 * scale

        self.x += (base_x - self.x) * clamp(dt * 1.5, 0, 1)
        desired_y = clamp(self.spawn_y + target_dy, self.size / 2 + 10, HEIGHT - self.size / 2 - 10)
        self.y += (desired_y - self.y) * clamp(dt * 2.0, 0, 1)

        self.attack_cooldown -= dt
        if self.attack_cooldown <= 0 and self.type != EnemyType.MELEE_EYE:
            self._ranged_attack(bullets, sounds, player)
            if self.gunner:
                base_interval = 0.5
            elif self.laser_gun:
                base_interval = random.uniform(0.7, 1.2)
            else:
                base_interval = random.uniform(0.9, 1.6)
            self.attack_cooldown = max(0.15 if self.gunner else 0.4, base_interval / scale)
            if self.laser_gun and self.learner.counter_weapon() in ("B", "X"):
                # player's damage is coming mostly from a hit-and-run
                # weapon (Mjolnir throw / Infinity Ray) -- fire back
                # faster so standoff play is punished, same spirit as
                # the melee-boss distance-closing counter below.
                self.attack_cooldown *= 0.7

        if not self.gunner and not self.laser_gun:
            # everything except the ranged-only eye and General N can
            # also melee/charge
            self.melee_cooldown -= dt
            if self.melee_cooldown <= 0 and not self.charging:
                self._start_charge(player)
                if self.learner.counter_weapon() in ("B", "X"):
                    # player's damage is coming mostly from a hit-and-run
                    # weapon (Mjolnir throw / Infinity Ray) -- close
                    # distance more often so standoff play is punished.
                    self.melee_cooldown *= 0.7

        if self.charging:
            self._update_charge(dt, player, particles, sounds)

    def _ranged_attack(self, bullets, sounds, player):
        if self.type == EnemyType.SKULL_O_CTHULHU and self.breathes_fire:
            self._fire_breath(bullets, sounds, player)
            return
        if self.type == EnemyType.GUNNER_EYE:
            dx = player.x - self.x
            dy = player.y - self.y
            dist = max(1.0, math.hypot(dx, dy))
            speed = 380 * self.learner.scale()
            vx, vy = dx / dist * speed, dy / dist * speed
            bullets.append(Bullet(self.x, self.y, vx, vy, self.color, False, w=10, h=6))
            sounds.play("enemy_shoot")
            return
        if self.type == EnemyType.GENERAL_N and self.laser_gun:
            self._fire_laser(bullets, sounds, player)
            return

    def _fire_laser(self, bullets, sounds, player):
        """General N's laser cannons: a tight twin-bolt volley aimed at
        the player, replacing the old ram/charge attack."""
        dx = player.x - self.x
        dy = player.y - self.y
        base_angle = math.atan2(dy, dx)
        speed = 420 * self.learner.scale()
        for spread in (-0.05, 0.05):
            ang = base_angle + spread
            vx, vy = math.cos(ang) * speed, math.sin(ang) * speed
            bullets.append(Bullet(self.x, self.y, vx, vy, LASER_RED, False, w=22, h=4, kind="laser"))
        sounds.play("enemy_shoot")

    def _fire_breath(self, bullets, sounds, player):
        """Dragon's fire breath: a quick 3-shot volley fanned slightly,
        instead of one clean shot."""
        dx = player.x - self.x
        dy = player.y - self.y
        base_angle = math.atan2(dy, dx)
        speed = 360 * self.learner.scale()
        for spread in (-0.12, 0.0, 0.12):
            ang = base_angle + spread
            vx, vy = math.cos(ang) * speed, math.sin(ang) * speed
            bullets.append(Bullet(self.x, self.y, vx, vy, ORANGE, False, w=12, h=7))
        sounds.play("enemy_shoot")

    def _start_charge(self, player):
        self.charging = True
        self.charge_telegraph = 0.5
        self.charge_target = (player.x, player.y)

    def _update_charge(self, dt, player, particles, sounds):
        if self.charge_telegraph > 0:
            self.charge_telegraph -= dt
            return
        tx, ty = self.charge_target
        dx, dy = tx - self.x, ty - self.y
        dist = max(1.0, math.hypot(dx, dy))
        speed = 520 * self.learner.scale()
        step = speed * dt
        if step >= dist or dist < 30:
            # snap to the target point so the collision pass this same
            # frame still sees the boss overlapping where it charged to
            self.x, self.y = tx, ty
            self.charge_finished_this_frame = True
            self.charging = False
            if self.type == EnemyType.MELEE_EYE:
                self.melee_cooldown = random.uniform(0.9, 1.6)
            else:
                self.melee_cooldown = random.uniform(1.8, 3.0)
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step

    def melee_damage(self):
        return 2 if self.heavy_melee else 1

    def take_damage(self, amount, weapon_slot):
        if not self.alive or self.downed:
            return
        self.hp -= amount
        self.learner.observe_damage(weapon_slot, amount)
        # Difficulty ramps from either side of the fight now: the boss
        # "learns" both from landing its own hits (game.py, on a
        # successful melee) and from eating hits itself, here.
        self.learner.observe_hit_taken()
        if self.hp <= 0:
            self.hp = 0
            if self.regen:
                # Regen twins go into a "downed" limbo instead of dying
                # outright -- they only truly die if their partner also
                # falls within the regen window (handled by the game).
                self.downed = True
            else:
                self.alive = False

    def _evade_direction(self):
        """Pick a dodge direction, leaning toward the side the player
        dodges to LESS (per BossLearner.preferred_evade_direction),
        then record which way we actually went so the learner keeps
        adapting over the course of the fight."""
        direction = self.learner.preferred_evade_direction()
        self.learner.observe_dodge(direction)
        return direction

    def try_dodge_infinity_ray(self, beam_y):
        """Returns True if the boss successfully evades the beam."""
        if self.evasive:
            # GENERAL_N: consistently jukes the beam
            self.y += self._evade_direction() * 90
            self.y = clamp(self.y, self.size / 2 + 10, HEIGHT - self.size / 2 - 10)
            return random.random() < 0.7
        if self.dodge_infinity:
            # dragon: only dodges if it "saw it coming" (i.e. beam
            # fired from far away, giving it time to react = "casual" shot)
            dist = abs(beam_y - self.y)
            if dist > 260:
                self.y += self._evade_direction() * 70
                return random.random() < 0.55
            return False
        return False

    def draw(self, surface):
        if self.downed or not self.alive:
            return
        key = _BOSS_ART_KEYS[self.type]
        grid, palette = BOSS_ART[key]
        draw_sprite(surface, grid, palette, self.x, self.y, PIXEL_SCALE)

        # Phase flash: a brief bright ring in the new phase's color
        # right after a threshold is crossed, so the transition reads
        # clearly even if the player is mid-dodge and not looking at
        # the hp bar.
        if self.phase_flash_timer > 0:
            flash_color = BOSS_PHASE_COLORS[min(self.phase, len(BOSS_PHASE_COLORS) - 1)] or WHITE
            t = clamp(self.phase_flash_timer / 0.5, 0, 1)
            pygame.draw.circle(surface, flash_color, (int(self.x), int(self.y)),
                                int(self.size * (0.9 + (1 - t) * 0.6)), width=max(1, int(4 * t)))

        if self.charging and self.charge_telegraph > 0:
            pygame.draw.circle(surface, RED, (int(self.x), int(self.y)), int(self.size * 0.7), width=3)

        # hp bar, with small phase pips underneath showing where the
        # thresholds fall and which ones have been crossed
        bar_w = 90
        bar_x = self.x - bar_w / 2
        bar_y = self.y - self.size / 2 - 16
        pygame.draw.rect(surface, (40, 10, 10), (bar_x, bar_y, bar_w, 6))
        frac = clamp(self.hp / self.max_hp, 0, 1)
        bar_color = BOSS_PHASE_COLORS[min(self.phase, len(BOSS_PHASE_COLORS) - 1)] or (YELLOW if frac > 0.3 else RED)
        pygame.draw.rect(surface, bar_color, (bar_x, bar_y, bar_w * frac, 6))
        for threshold in BOSS_PHASE_THRESHOLDS:
            px = bar_x + bar_w * threshold
            pygame.draw.line(surface, (10, 10, 10), (px, bar_y), (px, bar_y + 6), 1)