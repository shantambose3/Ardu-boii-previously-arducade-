"""
Bullets and other flying projectiles: nails, mjolnir, bombs,
and the infinity ray beam. World is horizontal now, so travel is
mostly along X, and lifetime bounds use WIDTH instead of HEIGHT.
"""

import math

import pygame

from .constants import WIDTH, HEIGHT
from .helpers import clamp


class Bullet:
    def __init__(self, x, y, vx, vy, color, is_player, w=10, h=4, damage=1, kind="nail"):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.color = color
        self.is_player = is_player
        self.w, self.h = w, h
        self.alive = True
        self.damage = damage
        self.kind = kind         

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < -30 or self.x > WIDTH + 30 or self.y < -30 or self.y > HEIGHT + 30:
            self.alive = False

    def rect(self):
        return pygame.Rect(int(self.x - self.w / 2), int(self.y - self.h / 2), self.w, self.h)

    def draw(self, surface):
        r = self.rect()
        if self.kind == "laser":
            # elongated, glowing bolt so Viltrum laser fire reads
            # differently from the small round "nail" bullets
            angle = math.atan2(self.vy, self.vx)
            length = max(self.w, self.h) * 1.0 + 10
            dx, dy = math.cos(angle), math.sin(angle)
            x0, y0 = self.x - dx * length / 2, self.y - dy * length / 2
            x1, y1 = self.x + dx * length / 2, self.y + dy * length / 2
            pygame.draw.line(surface, self.color, (x0, y0), (x1, y1), width=4)
            glow = tuple(clamp(c + 80, 0, 255) for c in self.color)
            pygame.draw.line(surface, glow, (x0, y0), (x1, y1), width=2)
            return
        pygame.draw.rect(surface, self.color, r, border_radius=1)
        glow = tuple(clamp(c + 60, 0, 255) for c in self.color)
        pygame.draw.rect(surface, glow, r.inflate(-2, -2), border_radius=1)


class Mjolnir:
    """Player throws their gun forward; it flies out, then boomerangs
    back to the player, damaging enemies both ways."""

    def __init__(self, x, y, color, speed, max_range, damage):
        self.x, self.y = x, y
        self.start_x, self.start_y = x, y
        self.color = color
        self.speed = speed
        self.max_range = max_range
        self.damage = damage
        self.returning = False
        self.alive = True
        self.spin = 0.0
        self.size = 14
        self.hit_enemies_out = set()
        self.hit_enemies_back = set()

    def update(self, dt, owner):
        self.spin += dt * 18
        if not self.returning:
            self.x += self.speed * dt
            if self.x - self.start_x >= self.max_range:
                self.returning = True
        else:
            dx = owner.x - self.x
            dy = owner.y - self.y
            dist = max(1.0, math.hypot(dx, dy))
            step = self.speed * dt
            if step >= dist:
                self.alive = False
            else:
                self.x += dx / dist * step
                self.y += dy / dist * step

    def rect(self):
        s = self.size
        return pygame.Rect(int(self.x - s / 2), int(self.y - s / 2), s, s)

    def draw(self, surface):
        cx, cy = int(self.x), int(self.y)
        s = self.size
        pts = []
        for i in range(4):
            ang = self.spin + i * math.pi / 2
            pts.append((cx + math.cos(ang) * s / 2, cy + math.sin(ang) * s / 2))
        pygame.draw.polygon(surface, self.color, pts)
        pygame.draw.circle(surface, (240, 240, 250), (cx, cy), 3)


class Bomb:
    """Lobbed bomb(Updated from the ragnar idea): arcs forward from the player, explodes the instant
    it touches an enemy, or after a short fuse if it doesn't hit
    anything first. Deals radius damage on detonation -- enemies only,
    never the player who threw it."""

    def __init__(self, x, y, vx, vy, color, damage, fuse, blast_radius):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.color = color
        self.damage = damage
        self.fuse = fuse
        self.blast_radius = blast_radius
        self.alive = True
        self.exploded = False
        self.size = 10
        self.spin = 0.0
        # tiny explosion flash timer for drawing the blast ring
        self.explosion_timer = 0.0
        self.explosion_max = 0.25

    def update(self, dt):
        if self.exploded:
            self.explosion_timer -= dt
            if self.explosion_timer <= 0:
                self.alive = False
            return
        self.spin += dt * 10
        self.vy += 420 * dt  # gravity, gives it an arc
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.fuse -= dt
        if self.fuse <= 0 or self.x > WIDTH + 20 or self.x < -20 or self.y > HEIGHT + 20:
            self.detonate()

    def detonate(self):
        if self.exploded:
            return
        self.exploded = True
        self.explosion_timer = self.explosion_max

    def rect(self):
        s = self.size
        return pygame.Rect(int(self.x - s / 2), int(self.y - s / 2), s, s)

    def blast_rect(self):
        r = self.blast_radius
        return pygame.Rect(int(self.x - r), int(self.y - r), int(r * 2), int(r * 2))

    def draw(self, surface):
        cx, cy = int(self.x), int(self.y)
        if self.exploded:
            t = clamp(self.explosion_timer / self.explosion_max, 0, 1)
            radius = int(self.blast_radius * (1 - t) + 6)
            ring_col = (255, int(200 * t) + 40, 40)
            pygame.draw.circle(surface, ring_col, (cx, cy), radius, width=3)
            core = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(core, (255, 160, 40, int(120 * t)), (radius, radius), radius)
            surface.blit(core, (cx - radius, cy - radius))
            return
        s = self.size
        pygame.draw.circle(surface, (30, 30, 35), (cx, cy), s // 2)
        pygame.draw.circle(surface, self.color, (cx, cy), s // 2, width=2)
        # lit fuse spark on top
        fx = cx + int(math.cos(self.spin) * 3)
        fy = cy - s // 2 - 2 + int(math.sin(self.spin * 2) * 2)
        pygame.draw.circle(surface, (255, 220, 60), (fx, fy), 2)


class InfinityBeam:
    """Space racer's iconic attack:Full-width beam sweeping across the play field at a fixed y,
    obliterates anything it touches (except bosses that can dodge/evade
    it). Horizontal strip spanning full WIDTH at the player's y."""

    def __init__(self, y, duration, width, color):
        self.y = y
        self.timer = duration
        self.max_timer = duration
        self.width = width
        self.color = color
        self.alive = True

    def update(self, dt):
        self.timer -= dt
        if self.timer <= 0:
            self.alive = False

    def rect(self):
        return pygame.Rect(0, int(self.y - self.width / 2), WIDTH, self.width)

    def draw(self, surface):
        t = clamp(self.timer / self.max_timer, 0, 1)
        alpha_width = self.width * (0.4 + 0.6 * t)
        r = pygame.Rect(0, int(self.y - alpha_width / 2), WIDTH, int(alpha_width))
        core = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
        core.fill((*self.color, 160))
        surface.blit(core, r.topleft)
        pygame.draw.rect(surface, (255, 255, 255), r, width=2)