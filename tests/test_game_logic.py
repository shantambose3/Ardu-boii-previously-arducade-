"""
Lightweight headless "does the game logic actually hold together" pass.

Deliberately kept small -- a handful of state-machine/boundary checks
plus one short smoke-run of the real update() loop -- not an
exhaustive simulation. Goal is to catch obvious glitches/loopholes
(wave-counter off-by-ones, boss-trigger edge, dead state transitions),
not full coverage.

Run from ardu-cade/ (no real display needed):
    pip install pytest pygame-ce numpy --break-system-packages
    SDL_VIDEODRIVER=dummy PYTHONPATH=python/galactic_raiders pytest tests/test_game_logic.py -v
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python", "galactic_raiders"))

import pygame  # noqa: E402
pygame.init()

from game.game import Game  # noqa: E402
from game.constants import GameState, Layer, WAVES_PER_LAYER  # noqa: E402


def new_game():
    return Game(fullscreen=False)


# ---------------------------------------------------------------------
# State machine boundaries
# ---------------------------------------------------------------------

def test_start_new_game_lands_on_layer_select():
    g = new_game()
    g.start_new_game()
    assert g.state == GameState.LAYER_SELECT
    assert g.menu_cursor == 0


def test_choose_layer_resets_wave_to_one():
    g = new_game()
    g.start_new_game()
    g.choose_layer(Layer.TERRIBLE_TWINS)
    assert g.wave == 1
    assert g.state == GameState.PLAYING
    assert g.layer == Layer.TERRIBLE_TWINS


def test_next_wave_increments_normally():
    g = new_game()
    g.start_new_game()
    g.choose_layer(Layer.VILTRUM_INVASION)
    g.next_wave()
    assert g.wave == 2
    assert g.state == GameState.PLAYING


def test_wave_overflow_triggers_boss_not_a_wave_11():
    """This is the classic off-by-one spot: wave must never exceed
    WAVES_PER_LAYER while still in PLAYING -- crossing that boundary
    should hand off to the boss instead."""
    g = new_game()
    g.start_new_game()
    g.choose_layer(Layer.VILTRUM_INVASION)
    for _ in range(WAVES_PER_LAYER - 1):
        g.next_wave()
    assert g.wave == WAVES_PER_LAYER
    assert g.state == GameState.PLAYING
    g.next_wave()  # crosses the boundary
    assert g.wave == WAVES_PER_LAYER + 1
    assert g.state != GameState.PLAYING  # must have handed off to the boss
    assert g.state in (GameState.BOSS_FIGHT, GameState.BOSS_INTRO)


def test_1_2_3_shortcuts_still_work_in_layer_select():
    """Task 5 explicitly keeps the keyboard 1/2/3 shortcuts (dev-testing
    convenience) even though the hardware D8/D9/D10 instant-jump was
    removed -- regression check that those keys are untouched."""
    g = new_game()
    g.start_new_game()
    assert g.state == GameState.LAYER_SELECT
    layers = list(Layer)
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_2, mod=0)
    g.handle_event(ev)
    assert g.menu_cursor == 1
    ev_enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0)
    g.handle_event(ev_enter)
    assert g.layer == layers[1]
    assert g.state == GameState.PLAYING


def test_lives_reaching_zero_reaches_defeat_eventually():
    g = new_game()
    g.start_new_game()
    g.choose_layer(Layer.VILTRUM_INVASION)
    g.player.lives = 1
    g.player.hit(g.particles, g.sounds)  # the real "take a hit" path
    assert g.player.alive is False
    assert g.player.lives == 0
    # Drive a handful of update ticks with no input -- alive=False's
    # branch in _update_playing() waits for in-flight particles to
    # clear (len(self.particles) == 0) before flipping to DEFEAT, so
    # this needs a few real ticks, not just the one hit() call.
    keys = pygame.key.get_pressed()
    for _ in range(180):
        g.update(1 / 60.0, keys, [])
        if g.state == GameState.DEFEAT:
            break
    assert g.state == GameState.DEFEAT


# ---------------------------------------------------------------------
# Smoke run: does update() survive a few seconds of real ticks?
# ---------------------------------------------------------------------

def test_short_headless_playthrough_does_not_crash():
    g = new_game()
    g.start_new_game()
    g.choose_layer(Layer.VILTRUM_INVASION)
    keys = pygame.key.get_pressed()
    for _ in range(180):  # ~3 seconds at 60Hz
        pygame.event.pump()
        g.update(1 / 60.0, keys, pygame.event.get())
        g.draw()  # exercises the render path too (dummy surface, no window)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
