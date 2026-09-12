"""
Scrolling starfield background: Stars scrolls right-to-left to match
the horizontal orientation of the game.
"""

import random

import pygame

from .constants import WIDTH, HEIGHT
from .helpers import clamp


class Starfield:
    def __init__(self, count=140):
        self.stars = []
        for _ in range(count):
            self.stars.append([
                random.uniform(0, WIDTH),
                random.uniform(0, HEIGHT),
                random.uniform(30, 170),   
                random.uniform(1, 3),      
            ])

    def update(self, dt):
        for star in self.stars:
            star[0] -= star[2] * dt
            if star[0] < 0:
                star[0] = WIDTH
                star[1] = random.uniform(0, HEIGHT)

    def draw(self, surface):
        for x, y, speed, size in self.stars:
            brightness = clamp(int(90 + speed), 90, 255)
            color = (brightness, brightness, brightness)
            pygame.draw.circle(surface, color, (int(x), int(y)), int(size / 2) + 1)
