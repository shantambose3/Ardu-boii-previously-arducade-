"""
SPACE-RACER: THE JOURNEY BEYOND
An 8-bit horizontal arcade racer-shooter, built with pygame-ce.

*** NOT the UNO Q entry point. *** App Lab always runs
python/main.py (the Bridge-based one) automatically. This file is
only here for keyboard-only desktop testing of the game logic away
from the actual hardware. Do NOT call game.start_motion_sensor() from
here: that opens a direct I2C connection to the GY-521, which
conflicts with sketch/sketch.ino already mastering that same bus on
real hardware.

Controls:
    ARROWS / WASD           - move (bike + alien racer)
    Z / J                   - A: Vacuum Nails (continuous stream)
    X / K                   - B: Mjolnir (boomerang gun throw)
    C / L                   - X: Infinity Ray (3 uses per layer run)
    V / I                   - Y: Bomb (lob forward, explodes on contact or fuse)
    ENTER                   - confirm / start / restart
    UP / DOWN                - menu navigation
    ESC                      - quit / back

Run with:  python3 main.py   (from inside python/galactic_raiders/,
                               desktop only -- keyboard input only,
                               no controller/motion, for dev use)
Requires:  pip install pygame-ce
"""

import sys

import pygame

from game import Game


def main():
    game = Game()

    try:
        game.run()
    except Exception:
        pygame.quit()
        raise
    sys.exit(0)


if __name__ == "__main__":
    main()
