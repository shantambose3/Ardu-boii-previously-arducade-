"""
The player: an 8-bit space-bike ridden by a green alien racer.
Handles movement (now on the left side of a horizontal field, moving
in a 2D box), the 4-button weapon kit (A/B/X/Y), hit/respawn handling,
and drawing.
"""

import random

import pygame

from .constants import (
    WIDTH, HEIGHT, PLAYER_COLOR, PLAYER_SPEED, PLAYER_INVULN_TIME,
    PLAYER_START_LIVES, YELLOW, CYAN, WHITE, ORANGE, RED, PURPLE,
    NAILS_BULLET_SPEED, NAILS_FIRE_COOLDOWN, NAILS_DAMAGE,
    MJOLNIR_SPEED, MJOLNIR_COOLDOWN, MJOLNIR_DAMAGE, MJOLNIR_MAX_RANGE,
    INFINITY_RAY_USES_PER_LAYER, INFINITY_RAY_DURATION, INFINITY_RAY_LENGTH,
    BOMB_COOLDOWN, BOMB_SPEED_X, BOMB_SPEED_Y, BOMB_DAMAGE, BOMB_FUSE, BOMB_BLAST_RADIUS,
    PIXEL_SCALE, TILT_DODGE_COOLDOWN, TILT_DODGE_SPEED, TILT_DODGE_INVULN,
    SHOUT_OVERCHARGE_MULTIPLIER,
)
from .helpers import clamp
from .bullets import Bullet, Mjolnir, Bomb, InfinityBeam
from .particles import spawn_explosion
from .pixel_art import draw_sprite, PLAYER_GRID, PLAYER_PALETTE, PLAYER_ICON_GRID


class Player:
    def __init__(self):
        self.x = WIDTH * 0.14
        self.y = HEIGHT / 2
        self.vx = 0.0
        self.vy = 0.0
        self.w, self.h = 56, 40
        self.lives = PLAYER_START_LIVES
        self.invuln_timer = 0.0
        self.alive = True

        # weapon cooldowns / ammo
        self.nails_cooldown = 0.0
        self.mjolnir_cooldown = 0.0
        self.mjolnir_active = None
        self.infinity_charges = INFINITY_RAY_USES_PER_LAYER
        self.bomb_cooldown = 0.0

        self.last_weapon_used = "A"
        self.facing = 1

        # Sensor-mapped mechanics (MPU6050 tilt / shake, MAX9814 shout)
        self.dodge_roll_cooldown = 0.0
        self.overcharge_ready = False   # set True by a sustained shout; consumed by the next weapon fire
        self.combo_count = 0
        self.combo_multiplier = 1.0
        self.combo_timer = 0.0
        self.best_combo_multiplier = 1.0  # highest combo hit this run; feeds MidRunVerdict

        # Mid-run AI verdict (see adaptive_ai.MidRunVerdict): a weapon
        # slot letter locked out for a few waves after a PUNISH verdict,
        # or None if nothing is locked. weapon_lock_waves_left counts
        # down once per next_wave() call, in game.py.
        self.locked_weapon = None
        self.weapon_lock_waves_left = 0

    def lock_weapon(self, slot_letter, waves):
        self.locked_weapon = slot_letter
        self.weapon_lock_waves_left = waves
        if slot_letter == "B" and self.mjolnir_active is None:
            pass  # in-flight mjolnir (if any) still resolves normally; only new throws are blocked

    def tick_weapon_lock(self):
        """Call once per wave transition. Returns True the wave the
        lock actually expires (for an unlock toast)."""
        if self.locked_weapon is None:
            return False
        self.weapon_lock_waves_left -= 1
        if self.weapon_lock_waves_left <= 0:
            self.locked_weapon = None
            self.weapon_lock_waves_left = 0
            return True
        return False

    def try_dodge_roll(self, tilt_x, tilt_y, sounds):
        """MPU6050 tilt -> dodge-roll: a quick directional burst plus
        brief invulnerability, gated by TILT_DODGE_COOLDOWN. tilt_x/
        tilt_y are each roughly -1..1 (see ControllerBridge.get_tilt()
        in python/main.py). Returns True if the dodge actually fired."""
        if not self.alive or self.dodge_roll_cooldown > 0:
            return False
        norm = max(0.05, (tilt_x ** 2 + tilt_y ** 2) ** 0.5)
        dx, dy = tilt_x / norm, tilt_y / norm
        burst = TILT_DODGE_SPEED * 0.14  # short burst, not a per-second speed
        self.x = clamp(self.x + dx * burst, self.w / 2 + 6, WIDTH * 0.90)
        self.y = clamp(self.y + dy * burst, self.h / 2 + 6, HEIGHT - self.h / 2 - 6)
        self.dodge_roll_cooldown = TILT_DODGE_COOLDOWN
        self.invuln_timer = max(self.invuln_timer, TILT_DODGE_INVULN)
        sounds.play("dodge")
        return True

    def arm_overcharge(self):
        """MAX9814 shout (sustained loud input) -> arms a one-shot
        damage/effect multiplier consumed by whichever weapon fires
        next (see fire_nails/throw_mjolnir/fire_infinity_ray/
        throw_bomb below)."""
        self.overcharge_ready = True

    def _consume_overcharge(self):
        if self.overcharge_ready:
            self.overcharge_ready = False
            return SHOUT_OVERCHARGE_MULTIPLIER
        return 1.0

    def register_kill(self, risky):
        """Combo/risky-play scoring: consecutive kills within
        COMBO_WINDOW of each other ramp the multiplier up; a kill
        landed close to a diving/charging enemy (risky is True, see
        game.py) gets an extra bump. Returns the multiplier that
        applied to THIS kill (caller applies it to the score)."""
        from .constants import COMBO_WINDOW, COMBO_MAX_MULTIPLIER, COMBO_STEP, COMBO_RISK_BONUS
        if self.combo_timer <= 0:
            self.combo_count = 0
            self.combo_multiplier = 1.0
        self.combo_count += 1
        self.combo_multiplier = min(COMBO_MAX_MULTIPLIER, 1.0 + (self.combo_count - 1) * COMBO_STEP)
        self.combo_timer = COMBO_WINDOW
        self.best_combo_multiplier = max(self.best_combo_multiplier, self.combo_multiplier)
        applied = self.combo_multiplier * (COMBO_RISK_BONUS if risky else 1.0)
        return applied

    def break_combo(self):
        self.combo_count = 0
        self.combo_multiplier = 1.0
        self.combo_timer = 0.0

    @property
    def rect(self):
        return pygame.Rect(int(self.x - self.w / 2), int(self.y - self.h / 2), self.w, self.h)

    def reset_for_layer(self):
        """Called when starting/re-entering a layer run."""
        self.infinity_charges = INFINITY_RAY_USES_PER_LAYER
        self.bomb_cooldown = 0.0

    def update(self, dt, keys):
        if not self.alive:
            return
        prev_x, prev_y = self.x, self.y
        mx = my = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            mx -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            mx += 1
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            my -= 1
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            my += 1
        if mx or my:
            norm = (mx ** 2 + my ** 2) ** 0.5
            self.x += (mx / norm) * PLAYER_SPEED * dt
            self.y += (my / norm) * PLAYER_SPEED * dt
        self.x = clamp(self.x, self.w / 2 + 6, WIDTH * 0.90)
        self.y = clamp(self.y, self.h / 2 + 6, HEIGHT - self.h / 2 - 6)

        # Velocity estimate, used by melee-only enemies (Viltrum grunts)
        # to lead a predictive ram rather than always charging the
        # player's position at the moment the dive started -- see
        # Enemy.start_dive in enemy.py.
        if dt > 0:
            self.vx = (self.x - prev_x) / dt
            self.vy = (self.y - prev_y) / dt

        if self.nails_cooldown > 0:
            self.nails_cooldown -= dt
        if self.mjolnir_cooldown > 0:
            self.mjolnir_cooldown -= dt
        if self.bomb_cooldown > 0:
            self.bomb_cooldown -= dt
        if self.invuln_timer > 0:
            self.invuln_timer -= dt
        if self.dodge_roll_cooldown > 0:
            self.dodge_roll_cooldown -= dt
        if self.combo_timer > 0:
            self.combo_timer -= dt
            if self.combo_timer <= 0:
                self.break_combo()

    # weapon A: vacuum nails (continuous stream) 
    def fire_nails(self, bullets, sounds):
        if not self.alive or self.nails_cooldown > 0 or self.locked_weapon == "A":
            return
        boost = self._consume_overcharge()
        bullets.append(Bullet(self.x + self.w / 2, self.y, NAILS_BULLET_SPEED, 0,
                               YELLOW, True, w=12, h=3, damage=NAILS_DAMAGE * boost, kind="nail"))
        self.nails_cooldown = NAILS_FIRE_COOLDOWN
        self.last_weapon_used = "A"
        sounds.play("overcharge_shoot" if boost > 1 else "shoot")

    #  weapon B: mjolnir boomerang
    def throw_mjolnir(self, sounds):
        if not self.alive or self.mjolnir_cooldown > 0 or self.mjolnir_active is not None or self.locked_weapon == "B":
            return
        boost = self._consume_overcharge()
        self.mjolnir_active = Mjolnir(self.x, self.y, CYAN, MJOLNIR_SPEED, MJOLNIR_MAX_RANGE, MJOLNIR_DAMAGE * boost)
        self.mjolnir_cooldown = MJOLNIR_COOLDOWN
        self.last_weapon_used = "B"
        sounds.play("overcharge_shoot" if boost > 1 else "shoot")

    #  weapon X: infinity ray (limited uses)
    def fire_infinity_ray(self, beams, sounds, bypass_lock=False):
        if not self.alive or self.infinity_charges <= 0:
            return False
        if self.locked_weapon == "X" and not bypass_lock:
            return False
        boost = self._consume_overcharge()
        beams.append(InfinityBeam(self.y, INFINITY_RAY_DURATION, INFINITY_RAY_LENGTH * (1.4 if boost > 1 else 1.0), PURPLE))
        self.infinity_charges -= 1
        self.last_weapon_used = "X"
        sounds.play("overcharge_shoot" if boost > 1 else "infinity_ray")
        return True

    #  weapon Y: bombs (lobbed, explode on contact or after a fuse)
    def throw_bomb(self, bombs, sounds):
        if not self.alive or self.bomb_cooldown > 0 or self.locked_weapon == "Y":
            return
        boost = self._consume_overcharge()
        bombs.append(Bomb(self.x + self.w / 2, self.y, BOMB_SPEED_X, BOMB_SPEED_Y,
                           ORANGE, BOMB_DAMAGE * boost, BOMB_FUSE, BOMB_BLAST_RADIUS * (1.3 if boost > 1 else 1.0)))
        self.bomb_cooldown = BOMB_COOLDOWN
        self.last_weapon_used = "Y"
        sounds.play("overcharge_shoot" if boost > 1 else "bomb")

    def hit(self, particles, sounds, amount=1):
        if self.invuln_timer > 0 or not self.alive:
            return False
        spawn_explosion(particles, self.x, self.y, PLAYER_COLOR, count=22, speed=220)
        sounds.play("player_hit")
        self.lives -= amount
        if self.lives <= 0:
            self.lives = 0
            self.alive = False
        else:
            self.invuln_timer = PLAYER_INVULN_TIME
        return True

    def draw(self, surface):
        if not self.alive:
            return
        if self.invuln_timer > 0 and int(self.invuln_timer * 10) % 2 == 0:
            return  # blink while invulnerable
        draw_sprite(surface, PLAYER_GRID, PLAYER_PALETTE, self.x, self.y, PIXEL_SCALE)
        # engine flicker (behind-bike exhaust, on the trailing/left edge)
        flicker = random.randint(6, 12)
        ex = self.x - self.w / 2 + 6
        pygame.draw.line(surface, ORANGE, (ex, self.y + 6), (ex - flicker, self.y + 6), 2)
        pygame.draw.line(surface, ORANGE, (ex, self.y + 12), (ex - flicker, self.y + 12), 2)

        if self.mjolnir_active:
            self.mjolnir_active.draw(surface)

    def draw_life_icon(self, surface, x, y):
        draw_sprite(surface, PLAYER_ICON_GRID, {"g": (110, 230, 90), "e": (20, 20, 25),
                                                  "b": PLAYER_COLOR}, x, y, 3.5)