"""
Enemy: entering / formation / diving state machine, movement paths,
melee/ranged attacks, and per-type drawing. Behavior branches by
which Layer the enemy belongs to:

  Layer 1 (Viltrum Invasion)   - grunts melee-only ram; brutes are
                                  laser_gun ranged attackers, tough
                                  hide, big hitboxes
  Layer 2 (Terrible Twins)     - weak, fast, ranged gunners
  Layer 3 (Beast Among Beasts) - tanky, erratic, can hit each other

World is horizontal: enemies enter from the right and hold formation
on the right two-thirds of the screen, diving/charging left toward
the player.
"""

import math
import random

import pygame

from .constants import (
    WIDTH, HEIGHT, EnemyState, EnemyType, ENEMY_STATS, Layer,
    MAGENTA, BLACK, WHITE, PURPLE, YELLOW, RED, ORANGE, PIXEL_SCALE,
    LASER_RED,
)
from .helpers import clamp, bezier_point
from .bullets import Bullet
from .pixel_art import draw_sprite, ENEMY_ART


class Enemy:
    def __init__(self, etype, slot_x, slot_y, spawn_side, entry_delay):
        self.type = etype
        stats = ENEMY_STATS[etype]
        self.max_hp = stats["hp"]
        self.hp = stats["hp"]
        self.score = stats["score"]
        self.dive_score = stats["dive_score"]
        self.color = stats["color"]
        self.size = stats["size"]
        self.melee_only = stats.get("melee_only", False)
        self.laser_gun = stats.get("laser_gun", False)
        self.layer = stats.get("layer")
        self.erratic = stats.get("erratic", False)

        self.slot_x, self.slot_y = slot_x, slot_y
        self.x, self.y = slot_x, slot_y

        spawn_y = -40 if spawn_side == "top" else HEIGHT + 40
        self.entry_p0 = (WIDTH + 60, spawn_y if spawn_side in ("top", "bottom") else slot_y)
        mid_y = slot_y + random.uniform(-70, 70)
        self.entry_p1 = (WIDTH * 0.75, mid_y)
        self.entry_p2 = (slot_x + random.uniform(40, 90), mid_y)
        self.entry_p3 = (slot_x, slot_y)
        self.x, self.y = self.entry_p0

        self.state = EnemyState.ENTERING
        self.entry_delay = entry_delay
        self.entry_t = 0.0
        self.entry_duration = random.uniform(1.6, 2.1)

        self.dive_cooldown = random.uniform(1.0, 4.0)
        self.dive_t = 0.0
        self.dive_duration = 2.6
        self.dive_path = None
        self.dive_fired = False
        # Return-leg state, used by melee-only grunts (see start_dive /
        # update): once the outbound ram reaches its target, they get
        # a second bezier curve back to formation instead of an
        # instant snap, symmetric with how they arrived.
        self.dive_returning = False
        self.return_path = None
        self.return_duration = 1.0
        self.return_t = 0.0

        self.alive = True
        self.wobble_phase = random.uniform(0, math.tau)

        # erratic beasts: random impulse drift, can friendly-fire
        self.impulse_timer = random.uniform(0.4, 1.4)
        self.impulse = (0, 0)

    @property
    def rect(self):
        s = self.size
        return pygame.Rect(int(self.x - s / 2), int(self.y - s / 2), s, s)

    def start_dive(self, player_x, player_y, dive_duration, player_vx=0.0, player_vy=0.0):
        self.state = EnemyState.DIVING
        self.dive_t = 0.0
        self.dive_duration = dive_duration
        self.dive_fired = False
        self.dive_returning = False
        self.return_path = None
        self.return_t = 0.0
        p0 = (self.x, self.y)

        if self.melee_only:
            # Free ram: melee grunts no longer charge a fixed
            # left-only lane straight out of formation. They lead the
            # player's current heading (simple linear prediction from
            # Player.vx/vy) and are free to swing through ANY part of
            # the screen -- top, bottom, or behind the player's
            # current position -- to reach that predicted point,
            # rather than always approaching from their formation row.
            lead_t = dive_duration * random.uniform(0.55, 0.85)
            predicted_x = clamp(player_x + player_vx * lead_t, 40, WIDTH - 40)
            predicted_y = clamp(player_y + player_vy * lead_t, 30, HEIGHT - 30)

            # A wide, randomized control point -- anywhere across the
            # full screen height (and well past the player horizontally
            # in either direction) -- so the approach curve genuinely
            # isn't restricted to a left-charge shape or the enemy's
            # own row anymore.
            swing_x = random.uniform(WIDTH * 0.15, WIDTH * 0.85)
            swing_y = random.uniform(20, HEIGHT - 20)
            p1 = (swing_x, swing_y)
            p2 = (predicted_x + random.uniform(-60, 60), predicted_y + random.uniform(-40, 40))
            p3 = (predicted_x, predicted_y)
        else:
            out_y = self.y + random.choice([-1, 1]) * random.uniform(90, 180)
            p1 = (self.x - random.uniform(120, 200), out_y)
            p2 = (WIDTH * random.uniform(0.35, 0.55), player_y + random.uniform(-90, 90))
            p3 = (self.slot_x, self.slot_y)

        self.dive_path = (p0, p1, p2, p3)

    def update(self, dt, formation_dy, player, bullets, sounds, dive_bullet_speed, other_enemies=None, speed_mult=1.0):
        # speed_mult: Layer III's ChaosDirector momentarily speeds up
        # erratic drift/dives during a FRENZY event (see formation.py).
        # 1.0 = normal, unaffected everywhere else.
        if self.state == EnemyState.ENTERING:
            if self.entry_delay > 0:
                self.entry_delay -= dt
                return
            self.entry_t += dt / self.entry_duration
            if self.entry_t >= 1.0:
                self.entry_t = 1.0
                self.state = EnemyState.FORMATION
                self.x, self.y = self.slot_x, self.slot_y
            else:
                self.x, self.y = bezier_point(self.entry_p0, self.entry_p1, self.entry_p2, self.entry_p3, self.entry_t)

        elif self.state == EnemyState.FORMATION:
            if self.erratic:
                self._update_erratic(dt, other_enemies, speed_mult=speed_mult)
            else:
                self.x = self.slot_x
                self.y = self.slot_y + formation_dy + math.sin(self.wobble_phase) * 2
                self.wobble_phase += dt * 0.5

        elif self.state == EnemyState.DIVING:
            if self.melee_only and self.dive_returning:
                # Return leg: mirrors the outbound ram -- a proper
                # bezier curve with its own wide swing point, not an
                # instant snap back to formation.
                self.return_t += dt / self.return_duration
                t = clamp(self.return_t, 0, 1)
                p0, p1, p2, p3 = self.return_path
                self.x, self.y = bezier_point(p0, p1, p2, p3, t)
                if self.return_t >= 1.0:
                    self.state = EnemyState.FORMATION
                    self.x, self.y = self.slot_x, self.slot_y
                return

            self.dive_t += dt / self.dive_duration
            t = clamp(self.dive_t, 0, 1)
            p0, p1, p2, p3 = self.dive_path
            self.x, self.y = bezier_point(p0, p1, p2, p3, t)

            if not self.melee_only and not self.dive_fired and 0.35 < t < 0.6:
                dx = player.x - self.x
                dy = player.y - self.y
                dist = max(1.0, math.hypot(dx, dy))
                vx = dx / dist * dive_bullet_speed
                vy = dy / dist * dive_bullet_speed
                if self.laser_gun:
                    bullets.append(Bullet(self.x, self.y, vx, vy, LASER_RED, False, w=18, h=4, kind="laser"))
                else:
                    bullets.append(Bullet(self.x, self.y, vx, vy, MAGENTA, False, w=8, h=4))
                sounds.play("enemy_shoot")
                self.dive_fired = True

            if self.dive_t >= 1.0:
                if self.melee_only:
                    # Outbound ram just finished -- kick off a mirrored
                    # return curve instead of teleporting home.
                    self._start_return_leg()
                else:
                    self.state = EnemyState.FORMATION
                    self.x, self.y = self.slot_x, self.slot_y

    def _start_return_leg(self):
        """Builds the melee grunt's return-to-formation bezier once its
        outbound ram reaches its target -- same duration/shape budget
        as the attack leg, just run in reverse toward slot_x/slot_y,
        so returning reads as a symmetric part of the same maneuver
        rather than a snap."""
        self.dive_returning = True
        self.return_t = 0.0
        self.return_duration = max(0.6, self.dive_duration * 0.7)
        p0 = (self.x, self.y)
        swing_x = random.uniform(WIDTH * 0.15, WIDTH * 0.85)
        swing_y = random.uniform(20, HEIGHT - 20)
        p1 = (swing_x, swing_y)
        p2 = (self.slot_x + random.uniform(-60, 60), self.slot_y + random.uniform(-40, 40))
        p3 = (self.slot_x, self.slot_y)
        self.return_path = (p0, p1, p2, p3)

    def _update_erratic(self, dt, other_enemies, speed_mult=1.0):
        """Beast-layer enemies drift with uncoordinated impulses instead
        of holding a clean formation line -- and can bump/hit each
        other, dealt with in the game's collision pass."""
        self.impulse_timer -= dt
        if self.impulse_timer <= 0:
            self.impulse_timer = random.uniform(0.5, 1.3)
            self.impulse = (random.uniform(-40, 10), random.uniform(-60, 60))
        self.x += self.impulse[0] * dt * speed_mult
        self.y += self.impulse[1] * dt * speed_mult
        self.x = clamp(self.x, WIDTH * 0.55, WIDTH - 40)
        self.y = clamp(self.y, 40, HEIGHT - 40)

    def draw(self, surface):
        x, y, s = self.x, self.y, self.size
        c = self.color
        key = self.type.name
        if key in ENEMY_ART:
            grid, palette = ENEMY_ART[key]
            draw_sprite(surface, grid, palette, x, y, max(2, int(s / max(len(r) for r in grid))))
        else:
            pts = [(x, y - s / 2), (x - s / 2, y - s / 6), (x - s / 3, y + s / 2),
                   (x, y + s / 6), (x + s / 3, y + s / 2), (x + s / 2, y - s / 6)]
            pygame.draw.polygon(surface, c, pts)
        if self.melee_only:
            # small red chevron marker indicating "melee only" threat
            pygame.draw.polygon(surface, RED, [(x, y - s / 2 - 6), (x - 4, y - s / 2 - 2), (x + 4, y - s / 2 - 2)])
        elif self.laser_gun:
            # small laser-bolt marker indicating a ranged laser threat
            pygame.draw.line(surface, LASER_RED, (x - 5, y - s / 2 - 4), (x + 5, y - s / 2 - 4), width=3)
