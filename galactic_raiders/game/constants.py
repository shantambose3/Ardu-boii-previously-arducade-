"""
Constants: window/timing settings, colors, tuning values, enums,
and per-layer / per-enemy / per-boss stat tables.

SPACE-RACER: THE JOURNEY BEYOND
Horizontal 8-bit arcade shooter -- 3 layers x 10 waves + boss each.
"""

from enum import Enum, auto

# Window / timing  (HORIZONTAL layout now, not vertical)

WIDTH, HEIGHT = 960, 540
FPS = 60
PIXEL_SCALE = 3          # logical "8-bit pixel" size on screen

# Colors
BLACK = (4, 4, 10)
WHITE = (235, 235, 245)
CYAN = (80, 220, 255)
MAGENTA = (255, 70, 210)
YELLOW = (255, 220, 60)
RED = (255, 70, 70)
GREEN = (80, 255, 140)
ORANGE = (255, 150, 50)
DIM_BLUE = (40, 60, 110)
PURPLE = (170, 100, 255)
ALIEN_GREEN = (110, 230, 90)
ALIEN_GREEN_DARK = (60, 150, 60)
CHROME = (200, 210, 220)
CHROME_DARK = (120, 130, 140)
LASER_RED = (255, 40, 40)  # Viltrum brute/General N laser bolts


# Player tuning

PLAYER_COLOR = (90, 230, 255)
PLAYER_SPEED = 320.0          # px/sec(not lore accurate by the way)
PLAYER_INVULN_TIME = 2.2
PLAYER_START_LIVES = 5                 # "5 lives per shot" -> 5 hit points
PLAYER_LIVES_PER_STOCK = 5


# Weapon tuning  (A / B / X / Y)

class WeaponSlot(Enum):
    A_VACUUM_NAILS = auto()
    B_MJOLNIR = auto()
    X_INFINITY_RAY = auto()
    Y_BOMBS = auto()

# A - Vacuum Nails: continuous stream of small fast bullets
NAILS_BULLET_SPEED = 720.0
NAILS_FIRE_COOLDOWN = 0.09
NAILS_DAMAGE = 2

# B - Mjolnir: thrown gun, boomerangs back, hits multiple enemies along path
MJOLNIR_SPEED = 560.0
MJOLNIR_COOLDOWN = 0.9
MJOLNIR_DAMAGE = 5
MJOLNIR_MAX_RANGE = 340.0

# X - Infinity Ray: 3 uses per 10 waves (per layer run), full-screen beam
INFINITY_RAY_USES_PER_LAYER = 3
INFINITY_RAY_DAMAGE = 999           # obliterates on hit
INFINITY_RAY_DURATION = 0.45
INFINITY_RAY_LENGTH = 26

# Y - Bombs: lob a bomb forward, explodes on enemy contact or after a
# short fuse, radius damage to enemies only
BOMB_COOLDOWN = 1.4
BOMB_SPEED_X = 340.0
BOMB_SPEED_Y = -260.0
BOMB_DAMAGE = 14
BOMB_FUSE = 1.1
BOMB_BLAST_RADIUS = 60.0


# Enemy tuning

ENEMY_BULLET_SPEED = 300.0


# Misc

FONT_NAME = "couriernew,consolas,dejavusansmono,monospace"
GAME_TITLE = "SPACE-RACER: THE JOURNEY BEYOND"

EXTRA_LIFE_SCORES = [10000, 30000, 60000, 100000]

WAVES_PER_LAYER = 10

# Enums

class GameState(Enum):
    START = auto()          # title screen (image 3 style)
    LAYER_SELECT = auto()   # choose layer 1/2/3
    PLAYING = auto()
    WAVE_CLEAR = auto()
    BOSS_INTRO = auto()
    BOSS_FIGHT = auto()
    POST_BOSS_CHOICE = auto()   # continue same / different layer / quit
    QUIT_CONFIRM = auto()       # quitting screen (image 2 style)
    DEFEAT = auto()              # game over screen
    PAUSED = auto()               # pause menu (Resume/Restart/Quit), D12 toggles (image 1 style)
    AI_REPORT_CARD = auto()       # post-run summary of what the adaptive AI learned
    ENTER_INITIALS = auto()       # arcade-style 3-letter initials entry for the leaderboard
    LEADERBOARD = auto()          # local top-5 leaderboard display
    CAMPAIGN_COMPLETE = auto()    # all 3 layers' bosses cleared in one continuous run


class EnemyState(Enum):
    ENTERING = auto()
    FORMATION = auto()
    DIVING = auto()
    DEAD = auto()


class Layer(Enum):
    VILTRUM_INVASION = 1
    TERRIBLE_TWINS = 2
    BEAST_AMONG_BEASTS = 3


LAYER_NAMES = {
    Layer.VILTRUM_INVASION: "LAYER I: VILTRUM INVASION",
    Layer.TERRIBLE_TWINS: "LAYER II: TERRIBLE TWINS",
    Layer.BEAST_AMONG_BEASTS: "LAYER III: BEAST AMONG BEASTS",
}

LAYER_SUBTITLES = {
    Layer.VILTRUM_INVASION: "Armored soldiers. Grunts ram you, brutes and General N pack lasers.",
    Layer.TERRIBLE_TWINS: "Advanced fast gunners. Fragile but relentless.",
    Layer.BEAST_AMONG_BEASTS: "Feral space beasts. Chaotic, tanky, and uncoordinated.",
}


class EnemyType(Enum):
    # Layer 1 - Viltrum Invasion (melee only, tough hide, big hitboxes)
    VILTRUM_GRUNT = auto()
    VILTRUM_BRUTE = auto()
    GENERAL_N = auto()  # boss

    # Layer 2 - Terrible Twins (weak, fast, ranged)
    TWIN_DRONE = auto()
    TWIN_SNIPER = auto()
    GUNNER_EYE = auto()  # boss twin A -- ranged
    MELEE_EYE = auto()   # boss twin B -- melee

    # Layer 3 - Beast Among Beasts (tanky, uncoordinated, friendly fire)
    BEAST_SNAPPER = auto()
    BEAST_STALKER = auto()
    SKULL_O_CTHULHU = auto()  # boss


ENEMY_STATS = {
    # Layer 1: Viltrum Invasion
    # Hard to damage, easier to hit (big hitbox). Grunts are still
    # melee-only ramming troops; brutes and General N are laser-armed
    # ranged attackers (laser_gun) instead of melee.
    EnemyType.VILTRUM_GRUNT: {
        "score": 120, "dive_score": 220, "hp": 20, "color": (150, 170, 190),
        "size": 26, "melee_only": True, "layer": Layer.VILTRUM_INVASION,
    },
    EnemyType.VILTRUM_BRUTE: {
        "score": 200, "dive_score": 360, "hp": 30, "color": (110, 130, 150),
        "size": 32, "melee_only": False, "layer": Layer.VILTRUM_INVASION,
        "laser_gun": True,
    },
    EnemyType.GENERAL_N: {
        "score": 5000, "dive_score": 5000, "hp": 130, "color": (230, 230, 240),
        "size": 16 * PIXEL_SCALE, "melee_only": False, "layer": Layer.VILTRUM_INVASION,
        "boss": True, "evasive": True, "laser_gun": True,
    },

    # Layer 2: Terrible Twins
    # Highly advanced, very weak, fast gunners.
    EnemyType.TWIN_DRONE: {
        "score": 60, "dive_score": 100, "hp": 10, "color": (255, 120, 200),
        "size": 16, "melee_only": False, "layer": Layer.TERRIBLE_TWINS,
    },
    EnemyType.TWIN_SNIPER: {
        "score": 90, "dive_score": 150, "hp": 10, "color": (255, 170, 230),
        "size": 18, "melee_only": False, "layer": Layer.TERRIBLE_TWINS,
    },
    EnemyType.GUNNER_EYE: {
        "score": 6000, "dive_score": 6000, "hp": 55, "color": (255, 90, 90),
        "size": 16 * PIXEL_SCALE, "melee_only": False, "layer": Layer.TERRIBLE_TWINS,
        "boss": True, "regen": True, "gunner": True,
    },
    EnemyType.MELEE_EYE: {
        "score": 6000, "dive_score": 6000, "hp": 65, "color": (140, 60, 100),
        "size": 16 * PIXEL_SCALE, "melee_only": True, "layer": Layer.TERRIBLE_TWINS,
        "boss": True, "regen": True, "heavy_melee": True,
    },

    # Layer 3: Beast Among Beasts
    # Hard to hit AND hard to damage, uncoordinated (friendly fire).
    EnemyType.BEAST_SNAPPER: {
        "score": 150, "dive_score": 260, "hp": 5, "color": (180, 90, 40),
        "size": 24, "melee_only": False, "layer": Layer.BEAST_AMONG_BEASTS,
        "erratic": True,
    },
    EnemyType.BEAST_STALKER: {
        "score": 220, "dive_score": 320, "hp": 6, "color": (140, 60, 100),
        "size": 28, "melee_only": False, "layer": Layer.BEAST_AMONG_BEASTS,
        "erratic": True,
    },
    EnemyType.SKULL_O_CTHULHU: {
        "score": 8000, "dive_score": 8000, "hp": 150, "color": (200, 40, 30),
        "size": 16 * PIXEL_SCALE, "melee_only": False, "layer": Layer.BEAST_AMONG_BEASTS,
        "boss": True, "heavy_melee": True, "dodge_infinity": True, "breathes_fire": True,
    },
}

LAYER_ENEMY_TYPES = {
    Layer.VILTRUM_INVASION: [EnemyType.VILTRUM_GRUNT, EnemyType.VILTRUM_BRUTE],
    Layer.TERRIBLE_TWINS: [EnemyType.TWIN_DRONE, EnemyType.TWIN_SNIPER],
    Layer.BEAST_AMONG_BEASTS: [EnemyType.BEAST_SNAPPER, EnemyType.BEAST_STALKER],
}

LAYER_BOSS_TYPES = {
    Layer.VILTRUM_INVASION: [EnemyType.GENERAL_N],
    Layer.TERRIBLE_TWINS: [EnemyType.GUNNER_EYE, EnemyType.MELEE_EYE],
    Layer.BEAST_AMONG_BEASTS: [EnemyType.SKULL_O_CTHULHU],
}


# ---------------------------------------------------------------------
# Software update additions (see CHANGELOG.md)
# ---------------------------------------------------------------------

# Weapon slot letter -> display name, used by AI toasts / boss taunts /
# the report card so callouts read like "COUNTERING MJOLNIR" instead
# of "COUNTERING B".
WEAPON_DISPLAY_NAMES = {
    "A": "VACUUM NAILS",
    "B": "MJOLNIR",
    "X": "INFINITY RAY",
    "Y": "BOMBS",
}

# Combo / risky-play scoring
COMBO_WINDOW = 2.2                 # seconds since last kill before combo resets
COMBO_MAX_MULTIPLIER = 4.0
COMBO_STEP = 0.25                  # multiplier gained per kill in-window
COMBO_RISK_BONUS = 1.5             # extra multiplier while diving/charging enemies are close (risky play)
COMBO_RISK_RADIUS = 160.0          # px -- "close" for the risk bonus above

# Boss phase system (visible behavior/appearance shift at hp thresholds)
BOSS_PHASE_THRESHOLDS = (0.66, 0.33)   # phase 2 starts <=66% hp, phase 3 starts <=33% hp
BOSS_PHASE_SPEED_SCALE = (1.0, 1.18, 1.4)
BOSS_PHASE_COLORS = (None, (255, 200, 90), (255, 70, 70))  # None = boss's own base color

# Sensor-mapped mechanics
TILT_DODGE_THRESHOLD = 0.55        # 0..1 tilt magnitude to trigger a dodge-roll
TILT_DODGE_COOLDOWN = 1.1          # seconds
TILT_DODGE_SPEED = 900.0           # px/sec burst
TILT_DODGE_INVULN = 0.35           # seconds of i-frames granted

SHAKE_PANIC_THRESHOLD = 0.6        # 0..1 jerk signal to trigger the panic bomb
SHAKE_PANIC_COOLDOWN = 8.0         # seconds
SHAKE_PANIC_RADIUS = 260.0         # px -- damages/clears enemies this close to the player

SHOUT_OVERCHARGE_THRESHOLD = 0.72  # 0..1 mic intensity considered "shouting"
SHOUT_OVERCHARGE_SUSTAIN = 0.35    # seconds it must stay above threshold
SHOUT_OVERCHARGE_MULTIPLIER = 2.0  # damage/radius multiplier on the next weapon use

ULTIMATE_COOLDOWN = 20.0           # seconds -- tilt+shout compound "ultimate" move
ULTIMATE_TILT_THRESHOLD = 0.8
ULTIMATE_SHOUT_THRESHOLD = 0.85
ULTIMATE_WINDOW = 0.5              # seconds tilt+shout must overlap within

STEALTH_LIGHT_THRESHOLD = 0.55     # fatigue_level (dim-room proxy) above this = "stealth" active
STEALTH_DIVE_SUPPRESSION = 0.4     # extra multiplicative ease on dive chance while in stealth

# Leaderboard
LEADERBOARD_SIZE = 5
INITIALS_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"


# ---------------------------------------------------------------------
# Config-file overrides (config/game_config.yaml or .json). Every call
# below just re-reads a value that already has a hardcoded default
# above, so a missing/partial config file is always a no-op -- see
# game/config.py for the lookup/fallback order.
# ---------------------------------------------------------------------
from . import config as _config  # noqa: E402

NAILS_DAMAGE = _config.get("weapons.nails_damage", NAILS_DAMAGE)
NAILS_FIRE_COOLDOWN = _config.get("weapons.nails_fire_cooldown", NAILS_FIRE_COOLDOWN)
MJOLNIR_DAMAGE = _config.get("weapons.mjolnir_damage", MJOLNIR_DAMAGE)
MJOLNIR_COOLDOWN = _config.get("weapons.mjolnir_cooldown", MJOLNIR_COOLDOWN)
BOMB_DAMAGE = _config.get("weapons.bomb_damage", BOMB_DAMAGE)
BOMB_BLAST_RADIUS = _config.get("weapons.bomb_blast_radius", BOMB_BLAST_RADIUS)

AGGRESSION_POSITION_WEIGHT = _config.get("adaptive_ai.aggression_position_weight", 0.4)
AGGRESSION_MOTION_WEIGHT = _config.get("adaptive_ai.aggression_motion_weight", 0.4)
AGGRESSION_MIC_WEIGHT = _config.get("adaptive_ai.aggression_mic_weight", 0.3)
DIVE_RATE_MIN_MULTIPLIER = _config.get("adaptive_ai.dive_rate_min_multiplier", 0.75)
DIVE_RATE_MAX_MULTIPLIER = _config.get("adaptive_ai.dive_rate_max_multiplier", 1.65)
FATIGUE_EASE_CAP = _config.get("adaptive_ai.fatigue_ease_cap", 0.35)

COMBO_WINDOW = _config.get("combo.window_seconds", COMBO_WINDOW)
COMBO_MAX_MULTIPLIER = _config.get("combo.max_multiplier", COMBO_MAX_MULTIPLIER)
COMBO_STEP = _config.get("combo.step_per_kill", COMBO_STEP)
COMBO_RISK_BONUS = _config.get("combo.risk_bonus", COMBO_RISK_BONUS)
COMBO_RISK_RADIUS = _config.get("combo.risk_radius", COMBO_RISK_RADIUS)

BOSS_PHASE_THRESHOLDS = (
    _config.get("boss_phases.phase_2_hp_fraction", BOSS_PHASE_THRESHOLDS[0]),
    _config.get("boss_phases.phase_3_hp_fraction", BOSS_PHASE_THRESHOLDS[1]),
)
BOSS_PHASE_SPEED_SCALE = tuple(_config.get("boss_phases.speed_scale", list(BOSS_PHASE_SPEED_SCALE)))

TILT_DODGE_THRESHOLD = _config.get("sensors.tilt_dodge_threshold", TILT_DODGE_THRESHOLD)
TILT_DODGE_COOLDOWN = _config.get("sensors.tilt_dodge_cooldown", TILT_DODGE_COOLDOWN)
SHAKE_PANIC_THRESHOLD = _config.get("sensors.shake_panic_threshold", SHAKE_PANIC_THRESHOLD)
SHAKE_PANIC_COOLDOWN = _config.get("sensors.shake_panic_cooldown", SHAKE_PANIC_COOLDOWN)
SHOUT_OVERCHARGE_THRESHOLD = _config.get("sensors.shout_overcharge_threshold", SHOUT_OVERCHARGE_THRESHOLD)
SHOUT_OVERCHARGE_SUSTAIN = _config.get("sensors.shout_overcharge_sustain", SHOUT_OVERCHARGE_SUSTAIN)
ULTIMATE_COOLDOWN = _config.get("sensors.ultimate_cooldown", ULTIMATE_COOLDOWN)
STEALTH_LIGHT_THRESHOLD = _config.get("sensors.stealth_light_threshold", STEALTH_LIGHT_THRESHOLD)
