"""
Particles: explosion fragments and floating score popups.
"""

import math
import random

import pygame

from .constants import FONT_NAME
from .helpers import clamp


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size")

    def __init__(self, x, y, vx, vy, life, color, size):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= 0.94
        self.vy *= 0.94
        self.life -= dt
        return self.life > 0

    def draw(self, surface):
        t = clamp(self.life / self.max_life, 0, 1)
        size = max(1, int(self.size * t))
        color = tuple(clamp(int(c * t + 10), 0, 255) for c in self.color)
        pygame.draw.rect(surface, color, (int(self.x) - size // 2, int(self.y) - size // 2, size, size))


class ScorePopup:
    def __init__(self, x, y, text, color):
        self.x, self.y = x, y
        self.text = text
        self.color = color
        self.life = 0.9
        self.max_life = 0.9

    def update(self, dt):
        self.y -= 40 * dt
        self.life -= dt
        return self.life > 0

    def draw(self, surface):
        t = clamp(self.life / self.max_life, 0, 1)
        font = pygame.font.SysFont(FONT_NAME, 16, bold=True)
        label = font.render(self.text, True, self.color)
        label.set_alpha(int(255 * t))
        surface.blit(label, label.get_rect(center=(int(self.x), int(self.y))))


def spawn_explosion(particles, x, y, color, count=18, speed=180):
    for _ in range(count):
        angle = random.uniform(0, math.tau)
        spd = random.uniform(speed * 0.3, speed)
        vx = math.cos(angle) * spd
        vy = math.sin(angle) * spd
        life = random.uniform(0.25, 0.55)
        size = random.uniform(3, 7)
        particles.append(Particle(x, y, vx, vy, life, color, size))


class AiToast:
    """Short-lived on-screen callout for a visible AI adaptation event:
    a spawn-bias shift, a boss's counter-strategy changing, a Layer III
    chaos event firing, overcharge arming, etc. -- the "AI adaptation,
    visible in real time" ask. Game.py stacks these below the HUD;
    oldest expires first."""

    def __init__(self, text, color=(255, 255, 255), life=2.6):
        self.text = text
        self.color = color
        self.life = life
        self.max_life = life

    def update(self, dt):
        self.life -= dt
        return self.life > 0

    def draw(self, surface, index=0, center_x=None):
        from .constants import WIDTH
        cx = center_x if center_x is not None else WIDTH / 2
        t = clamp(self.life / self.max_life, 0, 1)
        alpha = int(255 * min(1.0, t * 3))  # fade in fast, hold, fade out over the tail
        font = pygame.font.SysFont(FONT_NAME, 15, bold=True)
        label = font.render(self.text, True, self.color)
        label.set_alpha(alpha)
        y = 58 + index * 20
        bg = pygame.Surface((label.get_width() + 16, label.get_height() + 6), pygame.SRCALPHA)
        bg.fill((0, 0, 0, min(160, alpha)))
        surface.blit(bg, bg.get_rect(center=(int(cx), int(y))))
        surface.blit(label, label.get_rect(center=(int(cx), int(y))))
