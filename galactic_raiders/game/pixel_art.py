"""
8-bit pixel art: sprites are defined as small grids of palette-index
characters and rendered as blocks of squares (classic "big pixel" look).
Includes the player (space-bike + green alien), the 6 grunt enemy
variants, and the 4 bosses (16x16 grids), plus a helper to draw any
sprite centered at a world position.

'.' = transparent
any other single character = a palette color key looked up in the
sprite's own PALETTE dict.
"""

import random

import pygame


def draw_sprite(surface, grid, palette, cx, cy, px_size, flip_x=False):
    """Draw a pixel-grid sprite centered at (cx, cy). px_size = size of
    one logical pixel in screen pixels."""
    rows = grid
    h = len(rows)
    w = max(len(r) for r in rows)
    total_w = w * px_size
    total_h = h * px_size
    ox = cx - total_w / 2
    oy = cy - total_h / 2
    for ry, row in enumerate(rows):
        for rx, ch in enumerate(row):
            if ch == ".":
                continue
            color = palette.get(ch)
            if color is None:
                continue
            draw_rx = (w - 1 - rx) if flip_x else rx
            rect = pygame.Rect(
                int(ox + draw_rx * px_size), int(oy + ry * px_size),
                px_size + 1, px_size + 1,
            )
            pygame.draw.rect(surface, color, rect)


def sprite_bounds(grid, px_size):
    h = len(grid)
    w = max(len(r) for r in grid)
    return w * px_size, h * px_size


# PLAYER: space-bike with a green alien rider (facing "up"/forward = right,
# since the world is horizontal now and the player sits on the left side
# facing right toward the enemies).
PLAYER_PALETTE = {
    "b": (90, 200, 255),    # bike body - cyan/blue
    "B": (50, 140, 210),    # bike body shade
    "c": (200, 220, 235),   # chrome / windshield
    "g": (110, 230, 90),    # alien skin
    "G": (60, 150, 60),     # alien skin shade
    "e": (20, 20, 25),      # eyes / visor
    "o": (255, 150, 50),    # exhaust / engine glow
    "y": (255, 220, 60),    # headlamp
    "w": (235, 235, 245),
    "n": (150, 75, 0)      # helmet highlight
}

# 16 wide x 12 tall, bike + alien, facing right
PLAYER_GRID = [
    "................",
    "....yyyyy.......",
    "....yeeewy......",
    "....yeeceyccccg.",
    "....yyyyyc......",
    "...ynnnnny......",
    "..bBnnnnnBbGG...",
    ".bBByyyyBBb.Gg..",
    "bBBB.nn..BBb....",
    ".BB...nn.BB.....",
    ".......oob......",
    "........bo......",
]

# Small variant used for HUD life icons -- simplified bike silhouette
PLAYER_ICON_GRID = [
    "yyy...",
    "yeey..",
    "bbbbcc",
    "b.bb..",
]


# LAYER 1: Viltrum Invasion -- armored soldiers (grunts melee, brutes laser)
VILTRUM_PALETTE = {
    "a": (150, 170, 190),
    "A": (100, 120, 140),
    "e": (255, 60, 60),
    "w": (230, 230, 240),
}
VILTRUM_GRUNT_GRID = [
    "........",
    "..w.....",
    "..w.w...",
    "....w.w.",
    "......w.",
    "........",
]
VILTRUM_BRUTE_PALETTE = {
    "a": (110, 130, 150),
    "A": (70, 85, 100),
    "e": (255, 90, 40),
    "w": (200, 210, 220),
}
VILTRUM_BRUTE_GRID = [
    "awaAAawa",
    "awAeeAwa",
    "aAwaawAa",
    "aAAwwAAa",
    "aa....aa",
    "aa....aa",
    ".a....a.",
]

# 16x16 boss - GENERAL N, now a compact attack warship (nose pointed
# right toward the player, engines glowing at the tail on the left)
GENERAL_N_PALETTE = {
    "g": (215, 220, 232),
    "G": (140, 148, 165),
    "d": (35, 38, 46),
    "b": (90, 220, 255),
    "e": (235, 55, 55),
    "y": (255, 205, 60),
    "o": (255, 150, 55),
}
GENERAL_N_GRID = [
    "............dd....",
    "..........GGGGG...",
    "........ggggggggo.",
    ".e...ggggggggggyoo",
    "dGGGgggggggggggyoo",
    "dGGggggbbbgggggyoo",
    "edGGgggbbbbggggyoo",
    "edGGgggbbbbggggyoo",
    "dGGggggbbbgggggyoo",
    "dGGGgggggggggggyoo",
    ".e...ggggggggggyoo",
    "........ggggggggo.",
    "..........GGGGG...",
    "............dd....",
]


# LAYER 2: Terrible Twins -- weak fast gunner drones
TWIN_DRONE_PALETTE = {
    "p": (255, 120, 200),
    "P": (200, 70, 150),
    "e": (255, 255, 255),
}
TWIN_DRONE_GRID = [
    ".pPp.",
    "ppppp",
    ".pep.",
    "p.p.p",
]
TWIN_SNIPER_PALETTE = {
    "p": (255, 170, 230),
    "P": (200, 110, 180),
    "e": (255, 255, 255),
    "c": (90, 200, 255),
}
TWIN_SNIPER_GRID = [
    "..pPp..",
    ".ppcpp.",
    "ppepepp",
    ".p...p.",
    "cccccce",
]

GUNNER_EYE_PALETTE = {
    "r": (255, 90, 90),
    "R": (170, 40, 40),
    "e": (255, 255, 255),
    "p": (30, 20, 20),
    "c": (255, 210, 60),
    "m": (110, 110, 120),
}
GUNNER_EYE_GRID = [
    "....RrrrrrrR....",
    "..RrrrrrrrrrrR..",
    ".RrrrrrrrrrrrrR.",
    "RrrrreeeeeerrrrR",
    "RrrreeeeeeeerrrR",
    "RrreeeepppeeerrR",
    "RrreeeppppeeerrR",
    "RrreeeepppeeerrR",
    "RrrreeeeeeeerrrR",
    "RrrrreeeeeerrrrR",
    ".RrrrrrrrrrrrrR.",
    "..RrrrrrrrrrrR..",
    "....RrrrrrrR....",
    ".....mmmmccc....",
    ".....mmmmccc....",
    "......mmccc.....",
]

MELEE_EYE_PALETTE = {
    "b": (140, 60, 100),
    "B": (90, 30, 60),
    "e": (255, 240, 60),
    "p": (30, 20, 20),
    "t": (240, 235, 220),
}
MELEE_EYE_GRID = [
    "....BbbbbbbB....",
    "..BbbbbbbbbbbB..",
    ".BbbbbbbbbbbbbB.",
    "BbbbbeeeeeebbbbB",
    "BbbbeeeeeeeebbbB",
    "BbbeeeepppeeebbB",
    "BbbeeeppppeeebbB",
    "BbbeeeepppeeebbB",
    "BbbbeeeeeeeebbbB",
    "BbbbbeeeeeebbbbB",
    ".BbbbbbbbbbbbbB.",
    "..BbbbbbbbbbbB..",
    "...tBbbbbbbBt...",
    "..t..tt..tt..t..",
    ".t..............",
    "................",
]


# LAYER 3: Beast Among Beasts -- feral, uncoordinated space beasts
BEAST_SNAPPER_PALETTE = {
    "b": (180, 90, 40),
    "B": (120, 55, 20),
    "e": (255, 240, 60),
    "t": (240, 240, 240),
}
BEAST_SNAPPER_GRID = [
    ".bBb..bBb.",
    "bbbbbbbbbb",
    "bBebbbbeBb",
    "btttbbttt b",
    ".bb.bb.bb.",
]
BEAST_STALKER_PALETTE = {
    "b": (140, 60, 100),
    "B": (90, 30, 60),
    "e": (255, 240, 60),
}
BEAST_STALKER_GRID = [
    "..bBBb..",
    ".bbbbbb.",
    "bbebbebb",
    "bbbbbbbb",
    ".b.bb.b.",
    "b.b..b.b",
]

SKULL_O_CTHULHU_PALETTE = {
    "g": (70, 160, 120),
    "G": (35, 95, 70),
    "d": (14, 40, 30),
    "e": (255, 225, 110),
    "p": (120, 95, 140),
    "P": (65, 48, 80),
}
SKULL_O_CTHULHU_GRID = [
    "...d.........d...",
    "..dGd.......dGd..",
    ".dGGGGd...dGGGGd.",
    ".dgggggggggggggd.",
    "dgggggggggggggggd",
    "dGgggggggggggggGd",
    "dGGddgggggggddGGd",
    "dgddedgggggdeddgd",
    "dggdedgggggdedggd",
    "dgggggggggggggggd",
    ".dgggggggggggggd.",
    "..dGGGGGGGGGGGd..",
    "..P.p.P...P.p.P..",
    "..P.p.P.p.P.p.P..",
    "..P.p...p...p.P..",
    "....p...p...p....",
]


BOSS_ART = {
    "GENERAL_N": (GENERAL_N_GRID, GENERAL_N_PALETTE),
    "GUNNER_EYE": (GUNNER_EYE_GRID, GUNNER_EYE_PALETTE),
    "MELEE_EYE": (MELEE_EYE_GRID, MELEE_EYE_PALETTE),
    "SKULL_O_CTHULHU": (SKULL_O_CTHULHU_GRID, SKULL_O_CTHULHU_PALETTE),
}

ENEMY_ART = {
    "VILTRUM_GRUNT": (VILTRUM_GRUNT_GRID, VILTRUM_PALETTE),
    "VILTRUM_BRUTE": (VILTRUM_BRUTE_GRID, VILTRUM_BRUTE_PALETTE),
    "TWIN_DRONE": (TWIN_DRONE_GRID, TWIN_DRONE_PALETTE),
    "TWIN_SNIPER": (TWIN_SNIPER_GRID, TWIN_SNIPER_PALETTE),
    "BEAST_SNAPPER": (BEAST_SNAPPER_GRID, BEAST_SNAPPER_PALETTE),
    "BEAST_STALKER": (BEAST_STALKER_GRID, BEAST_STALKER_PALETTE),
}


DITHER_PALETTE = {
    "1": (235, 235, 240),
    "2": (170, 170, 180),
    "3": (100, 100, 110),
    "4": (55, 55, 62),
}

# Same dither trick as DITHER_PALETTE above, tinted green instead of
# grayscale -- used for the title screen's CRT-static texture so it
# reads as "old green phosphor monitor" rather than reusing the
# grayscale look already spoken for by the quit/defeat screens.
CRT_STATIC_PALETTE = {
    "1": (60, 150, 90),
    "2": (38, 105, 62),
    "3": (20, 65, 38),
    "4": (10, 38, 22),
}


DEFEAT_GLYPH_GRID = [
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
]

QUIT_GLYPH_GRID = [
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
]


def build_dither_noise(width, height, cell, density=0.28, seed=None):
    """Return a list of (rect, palette_key) tuples for a scattered
    monochrome dither-noise field, evoking the heavily-dithered
    grayscale look of the reference art."""
    rng = random.Random(seed)
    cells = []
    cols = width // cell
    rows = height // cell
    for ry in range(rows):
        for rx in range(cols):
            if rng.random() < density:
                key = rng.choices(["1", "2", "3", "4"], weights=[3, 4, 5, 3])[0]
                cells.append((rx * cell, ry * cell, key))
    return cells


def draw_dither_noise(surface, cells, cell, ox=0, oy=0, palette=None):
    pal = palette if palette is not None else DITHER_PALETTE
    for x, y, key in cells:
        color = pal[key]
        pygame.draw.rect(surface, color, (ox + x, oy + y, cell, cell))

