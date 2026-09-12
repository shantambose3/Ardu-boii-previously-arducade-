"""
Main Game class: owns all game state, runs the update/draw loop,
handles input, and renders every screen:

  START           - title screen ("SPACE-RACER: THE JOURNEY BEYOND")
  LAYER_SELECT    - choose one of the 3 layers
  PLAYING         - a wave (1..10) of enemies for the chosen layer
  WAVE_CLEAR      - brief "WAVE N CLEAR" banner between waves
  BOSS_INTRO      - boss name card before the fight
  BOSS_FIGHT      - the layer's boss encounter
  POST_BOSS_CHOICE- continue same layer / different layer / quit
  QUIT_CONFIRM    - quitting screen
  DEFEAT          - game over screen
"""

import math
import random

import pygame

from .constants import (
    WIDTH, HEIGHT, FPS, BLACK, WHITE, CYAN, YELLOW, RED, GREEN, DIM_BLUE,
    PURPLE, ORANGE, MAGENTA, GameState, EnemyType, ENEMY_STATS,
    EXTRA_LIFE_SCORES, Layer, LAYER_NAMES, LAYER_SUBTITLES,
    LAYER_BOSS_TYPES, LAYER_ENEMY_TYPES, WAVES_PER_LAYER, GAME_TITLE, PIXEL_SCALE,
    INFINITY_RAY_USES_PER_LAYER, ENEMY_BULLET_SPEED, WEAPON_DISPLAY_NAMES,
    COMBO_RISK_RADIUS, TILT_DODGE_THRESHOLD, SHAKE_PANIC_THRESHOLD,
    SHAKE_PANIC_COOLDOWN, SHAKE_PANIC_RADIUS, ULTIMATE_TILT_THRESHOLD,
    ULTIMATE_SHOUT_THRESHOLD, ULTIMATE_WINDOW, ULTIMATE_COOLDOWN,
    LEADERBOARD_SIZE, INITIALS_CHARSET,
)
from .helpers import draw_text, draw_pixel_title
from .sound import SoundBank
from .background import Starfield
from .particles import ScorePopup, AiToast, spawn_explosion
from .player import Player
from .formation import Formation
from .enemy import EnemyState, Enemy
from .boss import Boss, REGEN_WINDOW, REGEN_HEAL_FRACTION
from .adaptive_ai import PlayerProfile, ChaosDirector, MidRunVerdict
from .edge_impulse import EdgeImpulseClassifier, ShoutGestureDetector
from . import persistence
from .telemetry import TelemetryLogger
from .pixel_art import (
    draw_sprite, PLAYER_GRID, PLAYER_PALETTE, BOSS_ART,
    build_dither_noise, draw_dither_noise, DEFEAT_GLYPH_GRID, QUIT_GLYPH_GRID,
    DITHER_PALETTE, CRT_STATIC_PALETTE,
)

# Boss-intro card text derives from the enum member name, but Python
# identifiers can't hold an apostrophe, so this boss needs an override.
BOSS_DISPLAY_NAMES = {
    "SKULL_O_CTHULHU": "SKULL O' CTHULHU",
}


class Game:
    def __init__(self, fullscreen=True):
        pygame.init()
        self.sounds = SoundBank()

        self.screen = pygame.Surface((WIDTH, HEIGHT))

        if fullscreen:
            self._display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self._display = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption(GAME_TITLE)

        
        self._recompute_scaling()

        self.clock = pygame.time.Clock()
        self.starfield = Starfield()
        self.scanlines = self._build_scanlines()

        self.state = GameState.START

        self.player = Player()
        self.bullets = []
        self.bombs = []
        self.beams = []
        self.particles = []
        self.popups = []
        self.formation = None
        self.boss_group = []

        self.layer = Layer.VILTRUM_INVASION
        self.wave = 1
        self.score = 0
        self.awarded_extra_lives = set()
        self.state_timer = 0.0
        self.message = ""

        # --- persistence: profiles/leaderboard/settings survive reboots ---
        save = persistence.load_save()
        self.player_profiles = {l: PlayerProfile.from_dict(save.get("profiles", {}).get(l.name)) for l in Layer}
        self.leaderboard = save.get("leaderboard", [])
        self.high_score = save.get("high_score", 0)
        self.secret_found = save.get("secret_found", False)
        self.oled_stats_hidden = save.get("oled_stats_hidden", False)
        self._total_runs = save.get("total_runs", 0)

        self.regen_pending = {}  # boss instance -> time remaining to also kill partner

        self.motion_sensor = None  # set by python/main.py via BridgeMotionSensorAdapter
        self.mic_sensor = None     # set by python/main.py via BridgeMicSensorAdapter (MAX9814 on A3)
        self.haptics = None        # set by python/main.py to a HapticsBridge (D6/D7 motors); no-op if None
        self.fatigue_level = 0.0   # 0..1, set each frame from the A2 photoresistor; eases WAVE difficulty only

        # --- adaptive AI visibility / multi-axis tracking additions ---
        self.ai_toasts = []               # list[AiToast], stacked under the HUD
        self._last_known_favorite = {}    # layer -> weapon letter, for adaptation-toast diffing
        self._last_known_lane = {}        # layer -> lane index, for adaptation-toast diffing
        self._elapsed = 0.0               # running clock, used by reaction-time tracking
        self._reaction_pending_since = None
        self._reaction_start_y = 0.0
        self.telemetry = TelemetryLogger()
        self.ei_classifier = EdgeImpulseClassifier()
        self.shout_detector = ShoutGestureDetector()
        self.report_card_data = None
        self.initials_indices = [0, 0, 0]
        self.initials_cursor = 0
        self.completed_layers = set()
        self._campaign_announced = False

        # Layer III (Beast Among Beasts) runs a ChaosDirector instead of
        # the adaptive PlayerProfile loop -- see adaptive_ai.py. One
        # instance, reused across waves within a session so its own
        # timer doesn't reset every wave build.
        self.chaos_directors = {Layer.BEAST_AMONG_BEASTS: ChaosDirector()}
        self.boss_adds = []  # small enemy reinforcements spawned on a boss phase change

        # Mid-run AI verdict: fires once after Wave 5 of each layer run
        # clears -- see adaptive_ai.MidRunVerdict and _maybe_resolve_mid_run_verdict.
        self.mid_run_verdict = MidRunVerdict()

        # Sensor-mapped mechanic cooldowns/state (tilt dodge lives on
        # Player itself; these are the ones that are more "global").
        self.panic_bomb_cooldown = 0.0
        self.ultimate_cooldown = 0.0
        self._ultimate_tilt_timer = 0.0
        self.low_health_timer = 0.0

        self._pre_pause_state = None  # GameState to return to on Resume
        self.pause_cursor = 0         # menu_cursor equivalent for the pause menu

        self.menu_cursor = 0  # for layer select / post-boss menus

        # impact frames: brief full freeze of gameplay logic on a solid hit
        self.hitstop_timer = 0.0
        self.HITSTOP_DURATION = 0.06

        self._dither_cell = 6
        self._dither_cells = build_dither_noise(WIDTH, HEIGHT, self._dither_cell, density=0.22, seed=1)
        self._dither_refresh_timer = 0.0

        # Title-screen CRT treatment: a static green noise field plus a
        # precomputed vignette, both cached here since they're static.
        self._start_noise_cells = build_dither_noise(WIDTH, HEIGHT, self._dither_cell, density=0.045, seed=42)
        self._start_vignette = self._build_vignette()

        if self.sounds.music:
            self.sounds.music.start()

        self.running = True

    def _recompute_scaling(self):
        real_w, real_h = self._display.get_size()
        scale = min(real_w / WIDTH, real_h / HEIGHT)
        scaled_w = int(WIDTH * scale)
        scaled_h = int(HEIGHT * scale)
        self._scaled_size = (scaled_w, scaled_h)
        self._scale_offset = ((real_w - scaled_w) // 2, (real_h - scaled_h) // 2)

    def _present(self):
        """Scale the fixed-resolution internal surface onto the real
        display and flip. Call this instead of pygame.display.flip()
        directly. Falls back to a 1:1 blit if the real display happens
        to already be exactly WIDTHxHEIGHT (e.g. windowed dev mode)."""
        if self._display.get_size() == (WIDTH, HEIGHT):
            self._display.blit(self.screen, (0, 0))
        else:
            self._display.fill(BLACK)  # letterbox bars
            scaled = pygame.transform.scale(self.screen, self._scaled_size)
            self._display.blit(scaled, self._scale_offset)
        pygame.display.flip()

    def _build_scanlines(self):
        surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        for y in range(0, HEIGHT, 3):
            pygame.draw.line(surf, (0, 0, 0, 40), (0, y), (WIDTH, y))
        return surf

    def _build_vignette(self):
        """Precomputed radial darkening (coarse grid of alpha'd black
        rects, not a true per-pixel gradient -- plenty smooth at this
        cell size and far cheaper to build once at startup) used by the
        title screen to fake a CRT tube's corner falloff."""
        surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        cx, cy = WIDTH / 2, HEIGHT / 2
        max_dist = math.hypot(cx, cy)
        cell = 20
        for y in range(0, HEIGHT, cell):
            for x in range(0, WIDTH, cell):
                dist = math.hypot((x + cell / 2) - cx, (y + cell / 2) - cy)
                t = max(0.0, min(1.0, dist / max_dist)) ** 2.2
                alpha = int(160 * t)
                if alpha > 4:
                    pygame.draw.rect(surf, (0, 0, 0, alpha), (x, y, cell, cell))
        return surf

    def _buzz(self, event):
        """Fire a haptic buzz on the D6/D7 vibration motors for a game
        event ("explosion" / "infinity_ray" / "defeat" -- see
        HapticsBridge.PATTERNS in python/main.py). No-ops cleanly if
        self.haptics isn't set, same pattern as motion_sensor/mic_sensor
        being None on a desktop dev run with no MCU attached."""
        if self.haptics is not None:
            self.haptics.buzz(event)

    # state transitions
    def start_new_game(self):
        self.player = Player()
        self._clear_projectiles()
        self.particles.clear()
        self.popups.clear()
        self.ai_toasts.clear()
        self.boss_adds.clear()
        self.score = 0
        self.awarded_extra_lives = set()
        # NOTE: self.player_profiles is deliberately NOT reset here --
        # it's loaded from disk in __init__ and saved after each
        # wave/boss/quit, so the adaptive AI keeps "remembering" the
        # player across runs and across boots, not just within one run.
        self.completed_layers = set()
        self._campaign_announced = False
        self._total_runs += 1
        self.state = GameState.LAYER_SELECT
        self.menu_cursor = 0

    def _clear_projectiles(self):
        self.bullets.clear()
        self.player.mjolnir_active = None
        self.bombs.clear()
        self.beams.clear()

    def _save_progress(self):
        """Persist profiles/leaderboard/settings to disk. Cheap and
        called at natural checkpoints (wave clear, boss defeat, defeat,
        quit) rather than every frame."""
        data = {
            "version": persistence.SAVE_FORMAT_VERSION,
            "profiles": {l.name: p.to_dict() for l, p in self.player_profiles.items()},
            "leaderboard": self.leaderboard,
            "high_score": self.high_score,
            "secret_found": self.secret_found,
            "oled_stats_hidden": self.oled_stats_hidden,
            "total_runs": self._total_runs,
        }
        persistence.save_all(data)

    def _check_adaptation_toast(self, layer):
        """Compares the adaptive AI's current read on the player
        (favorite weapon / preferred lane) against what it was the
        last time a wave was built for this layer, and pushes a
        visible "AI ADAPTED..." toast the moment either one shifts --
        the "AI adaptation, visible in real time" ask."""
        if layer == Layer.BEAST_AMONG_BEASTS:
            return
        profile = self.player_profiles[layer]
        if profile.samples < 15:
            return
        fav_weapon = profile.favorite_weapon()
        fav_lane = profile.bias_spawn_lane(4)
        prev_weapon = self._last_known_favorite.get(layer)
        prev_lane = self._last_known_lane.get(layer)
        if prev_weapon is not None and fav_weapon != prev_weapon:
            name = WEAPON_DISPLAY_NAMES.get(fav_weapon, fav_weapon)
            self._push_ai_toast(f"AI ADAPTED: COUNTERING {name}")
        if prev_lane is not None and fav_lane != prev_lane:
            self._push_ai_toast(f"AI ADAPTED: INCREASED FLANKING (LANE {fav_lane + 1})")
        self._last_known_favorite[layer] = fav_weapon
        self._last_known_lane[layer] = fav_lane

    def _push_ai_toast(self, text, color=CYAN):
        self.ai_toasts.append(AiToast(text, color))
        self.sounds.play("ai_adapt")
        self.telemetry.log_event("ai_toast", text=text)
        if len(self.ai_toasts) > 4:
            self.ai_toasts.pop(0)

    def choose_layer(self, layer, fresh_player=False):
        self.layer = layer
        self.wave = 1
        self._clear_projectiles()
        self.boss_adds.clear()
        self.player.reset_for_layer()
        if fresh_player:
            self.player = Player()
            self.player.reset_for_layer()
        else:
            # re-entering/continuing: clear any weapon lock left over
            # from a previous layer run rather than carrying it in
            self.player.locked_weapon = None
            self.player.weapon_lock_waves_left = 0
        self.player_profiles[layer].reset_run_tallies()
        self.mid_run_verdict.reset()
        self._check_adaptation_toast(layer)
        self.formation = Formation(self.layer, self.wave, self.player_profiles[self.layer],
                                    fatigue_level=self.fatigue_level,
                                    chaos_director=self.chaos_directors.get(self.layer))
        self.state = GameState.PLAYING

    def next_wave(self):
        finished_wave = self.wave
        self.wave += 1
        self._clear_projectiles()

        _locked_before = self.player.locked_weapon
        if self.player.tick_weapon_lock():
            name = WEAPON_DISPLAY_NAMES.get(_locked_before, _locked_before) or "WEAPON"
            self._push_ai_toast(f"{name} RESTORED", color=GREEN)
            self.sounds.play("extra_life")

        if finished_wave == 5:
            self._maybe_resolve_mid_run_verdict()

        if self.wave > WAVES_PER_LAYER:
            self._begin_boss()
        else:
            self._check_adaptation_toast(self.layer)
            self.formation = Formation(self.layer, self.wave, self.player_profiles[self.layer],
                                        fatigue_level=self.fatigue_level,
                                        chaos_director=self.chaos_directors.get(self.layer))
            self.state = GameState.PLAYING

    def _maybe_resolve_mid_run_verdict(self):
        """After Wave 5 of a layer run clears, the AI hands down ONE
        verdict based on how the run has gone so far (see
        adaptive_ai.MidRunVerdict): either rewards a struggling player
        with 2 extra lives, or punishes a dominating one by locking
        out their deadliest weapon for a few waves. One-shot per
        layer run (mid_run_verdict.resolved), so re-clearing wave 5
        after a continue/retry doesn't re-trigger it."""
        if self.mid_run_verdict.resolved:
            return
        profile = self.player_profiles[self.layer]
        verdict, target = self.mid_run_verdict.decide(profile, self.player.best_combo_multiplier)
        self.telemetry.log_event("mid_run_verdict", verdict=verdict, target=target, layer=self.layer.name)
        if verdict == "PUNISH" and target is not None:
            self.player.lock_weapon(target, MidRunVerdict.WEAPON_LOCK_WAVES)
            name = WEAPON_DISPLAY_NAMES.get(target, target)
            self._push_ai_toast(f"AI VERDICT: {name} CONFISCATED", color=RED)
            self.sounds.play("chaos_event")
            self._buzz("defeat")
        else:
            self.player.lives += 2
            self._push_ai_toast("AI VERDICT: +2 LIVES AWARDED", color=GREEN)
            self.sounds.play("extra_life")
            self.popups.append(ScorePopup(WIDTH / 2, HEIGHT / 2, "AI GRANTS +2 LIVES", GREEN))

    def _begin_boss(self):
        self._clear_projectiles()
        self.boss_adds.clear()
        boss_types = LAYER_BOSS_TYPES[self.layer]
        if len(boss_types) == 1:
            self.boss_group = [Boss(boss_types[0], WIDTH * 0.8, HEIGHT / 2)]
        else:
            self.boss_group = [
                Boss(boss_types[0], WIDTH * 0.8, HEIGHT * 0.32),
                Boss(boss_types[1], WIDTH * 0.8, HEIGHT * 0.68),
            ]
        self.regen_pending = {}
        self.state = GameState.BOSS_INTRO
        self.state_timer = 2.4

    def _trigger_impact_frame(self, duration=None):
        """Brief hit-stop: freezes gameplay logic for a couple frames to
        sell the weight of a solid hit."""
        self.hitstop_timer = duration if duration is not None else self.HITSTOP_DURATION

    def add_score(self, amount, x=None, y=None, color=YELLOW):
        self.score += amount
        self.high_score = max(self.high_score, self.score)
        if x is not None:
            self.popups.append(ScorePopup(x, y, f"+{amount}", color))
        for threshold in EXTRA_LIFE_SCORES:
            if self.score >= threshold and threshold not in self.awarded_extra_lives:
                self.awarded_extra_lives.add(threshold)
                self.player.lives += 1
                self.sounds.play("extra_life")
                self.popups.append(ScorePopup(WIDTH / 2, HEIGHT / 2, "EXTRA LIFE!", GREEN))

    # update
    def update(self, dt, keys, events):
        self.starfield.update(dt)
        self._elapsed += dt

        for p in self.popups[:]:
            if not p.update(dt):
                self.popups.remove(p)
        for p in self.particles[:]:
            if not p.update(dt):
                self.particles.remove(p)
        for t in self.ai_toasts[:]:
            if not t.update(dt):
                self.ai_toasts.remove(t)

        if self.hitstop_timer > 0:
            self.hitstop_timer -= dt
            return  # freeze all gameplay logic for a couple frames (impact frame)

        if self.state == GameState.START:
            pass

        elif self.state == GameState.LAYER_SELECT:
            pass

        elif self.state == GameState.PLAYING:
            self._update_playing(dt, keys)

        elif self.state == GameState.WAVE_CLEAR:
            self.state_timer -= dt
            self._update_projectiles(dt)
            if self.state_timer <= 0:
                self.next_wave()

        elif self.state == GameState.BOSS_INTRO:
            self.state_timer -= dt
            if self.state_timer <= 0:
                self.state = GameState.BOSS_FIGHT

        elif self.state == GameState.BOSS_FIGHT:
            self._update_boss_fight(dt, keys)

        elif self.state == GameState.POST_BOSS_CHOICE:
            pass

        elif self.state == GameState.CAMPAIGN_COMPLETE:
            pass

        elif self.state == GameState.AI_REPORT_CARD:
            pass

        elif self.state == GameState.ENTER_INITIALS:
            pass

        elif self.state == GameState.LEADERBOARD:
            pass

        elif self.state == GameState.PAUSED:
            pass  # gameplay logic frozen; _pre_pause_state resumes on unpause

        elif self.state == GameState.QUIT_CONFIRM:
            self._dither_refresh_timer -= dt
            if self._dither_refresh_timer <= 0:
                self._dither_refresh_timer = 0.09
                self._dither_cells = build_dither_noise(
                    WIDTH, HEIGHT, self._dither_cell, density=0.22,
                    seed=random.randint(0, 999999))

        elif self.state == GameState.DEFEAT:
            self._dither_refresh_timer -= dt
            if self._dither_refresh_timer <= 0:
                self._dither_refresh_timer = 0.09
                self._dither_cells = build_dither_noise(
                    WIDTH, HEIGHT, self._dither_cell, density=0.26,
                    seed=random.randint(0, 999999))



    def _current_aggression_signal(self):
        """Blend real controller motion (if the GY-521 is present) and
        mic loudness (if the MAX9814 is present) with the existing
        screen-position proxy, so the adaptive AI reflects actual
        physical play intensity -- how hard the player is shaking the
        controller AND how loud they're playing/yelling -- instead of
        just position on screen. Falls back cleanly to whatever subset
        of sensors is actually connected."""
        position_signal = 1.0 if self.player.x > WIDTH * 0.4 else 0.2

        motion_signal = None
        if self.motion_sensor is not None:
            motion_signal = self.motion_sensor.get_intensity()

        mic_signal = None
        if self.mic_sensor is not None:
            mic_signal = self.mic_sensor.get_intensity()

        if motion_signal is None and mic_signal is None:
            return position_signal

        # position is always in the mix; motion/mic contribute if
        # present, and weights renormalize so missing sensors don't
        # just shrink the signal.
        from .constants import AGGRESSION_POSITION_WEIGHT, AGGRESSION_MOTION_WEIGHT, AGGRESSION_MIC_WEIGHT
        weights = [(AGGRESSION_POSITION_WEIGHT, position_signal)]
        if motion_signal is not None:
            weights.append((AGGRESSION_MOTION_WEIGHT, motion_signal))
        if mic_signal is not None:
            weights.append((AGGRESSION_MIC_WEIGHT, mic_signal))
        total_weight = sum(w for w, _ in weights)
        return sum(w * v for w, v in weights) / total_weight

    def _track_reaction_time(self, dt):
        """Lightweight proxy for reaction time: while any enemy bullet
        is in a "danger zone" close to the player, start a timer; the
        first time the player moves meaningfully (a dodge) while still
        in danger, record the elapsed time as one reaction-time sample.
        Not a perfect measurement, but a consistent, cheap signal that
        gets faster for players who dodge quickly and slower for ones
        who don't react until it's too late."""
        danger = any(
            (not b.is_player) and b.alive and abs(b.x - self.player.x) < 200 and abs(b.y - self.player.y) < 60
            for b in self.bullets
        )
        if danger:
            if self._reaction_pending_since is None:
                self._reaction_pending_since = self._elapsed
                self._reaction_start_y = self.player.y
            elif abs(self.player.y - self._reaction_start_y) > 24:
                rt = self._elapsed - self._reaction_pending_since
                self.player_profiles[self.layer].observe_reaction_time(rt)
                self._reaction_pending_since = None
        else:
            self._reaction_pending_since = None

    def _update_sensor_mechanics(self, dt):
        """Per-frame handling for the sensor-mapped mechanics: MPU6050
        tilt -> dodge-roll, MPU6050 shake -> panic bomb, MAX9814
        sustained shout -> weapon overcharge, and tilt+shout together
        -> a rare "ultimate" (also this game's secret/easter egg)."""
        tilt = self.motion_sensor.get_tilt() if self.motion_sensor is not None else None
        shake = self.motion_sensor.get_shake_intensity() if self.motion_sensor is not None else None
        mic = self.mic_sensor.get_intensity() if self.mic_sensor is not None else None

        if tilt is not None:
            tx, ty = tilt
            mag = (tx * tx + ty * ty) ** 0.5
            if mag >= TILT_DODGE_THRESHOLD:
                self.player.try_dodge_roll(tx, ty, self.sounds)

        if self.panic_bomb_cooldown > 0:
            self.panic_bomb_cooldown -= dt
        if shake is not None and shake >= SHAKE_PANIC_THRESHOLD and self.panic_bomb_cooldown <= 0:
            self._trigger_panic_bomb()

        if mic is not None:
            if self.shout_detector.update(dt, mic) and not self.player.overcharge_ready:
                self.player.arm_overcharge()
                self._push_ai_toast("OVERCHARGE READY!", color=ORANGE)
                self.sounds.play("overcharge_ready")

        if self.ultimate_cooldown > 0:
            self.ultimate_cooldown -= dt
        big_tilt = tilt is not None and (tilt[0] ** 2 + tilt[1] ** 2) ** 0.5 >= ULTIMATE_TILT_THRESHOLD
        loud = mic is not None and mic >= ULTIMATE_SHOUT_THRESHOLD
        if big_tilt:
            self._ultimate_tilt_timer = ULTIMATE_WINDOW
        elif self._ultimate_tilt_timer > 0:
            self._ultimate_tilt_timer -= dt
        if loud and self._ultimate_tilt_timer > 0 and self.ultimate_cooldown <= 0:
            self._trigger_ultimate()

        if self.player.alive and self.player.lives <= 1:
            self.low_health_timer -= dt
            if self.low_health_timer <= 0:
                self._buzz("low_health")
                self.low_health_timer = 2.0
        else:
            self.low_health_timer = 0.0

    def _trigger_panic_bomb(self):
        """MPU6050 shake -> screen-clear bomb / panic button: clears
        every live enemy bullet and chips damage into anything close
        to the player, on a long cooldown so it's a real "oh no"
        button, not a spam-friendly weapon."""
        self.panic_bomb_cooldown = SHAKE_PANIC_COOLDOWN
        cleared = 0
        for b in self.bullets:
            if not b.is_player and b.alive:
                dx, dy = b.x - self.player.x, b.y - self.player.y
                if dx * dx + dy * dy <= SHAKE_PANIC_RADIUS ** 2:
                    b.alive = False
                    cleared += 1
        spawn_explosion(self.particles, self.player.x, self.player.y, CYAN, count=30, speed=260)
        self.sounds.play("panic_bomb")
        self._buzz("explosion")
        self._push_ai_toast("PANIC BOMB: BULLETS CLEARED!", color=CYAN)
        self.telemetry.log_event("panic_bomb", cleared=cleared, layer=self.layer.name)
        if self.formation:
            for e in self.formation.alive_enemies():
                dx, dy = e.x - self.player.x, e.y - self.player.y
                if dx * dx + dy * dy <= SHAKE_PANIC_RADIUS ** 2:
                    e.hp -= 6
                    if e.hp <= 0:
                        self._kill_enemy(e)
        for boss in self.boss_group:
            if boss.alive and not boss.downed:
                dx, dy = boss.x - self.player.x, boss.y - self.player.y
                if dx * dx + dy * dy <= SHAKE_PANIC_RADIUS ** 2:
                    boss.take_damage(10, "Y")
                    if boss.downed or not boss.alive:
                        self._on_boss_downed(boss)

    def _trigger_ultimate(self):
        """Compound move: sustained big tilt + a shout within
        ULTIMATE_WINDOW of each other fires a bonus infinity-ray blast
        -- this game's rewarded-experimentation secret/easter egg,
        found by combining two sensors rather than by button-mashing."""
        self.ultimate_cooldown = ULTIMATE_COOLDOWN
        self._ultimate_tilt_timer = 0.0
        self.player.infinity_charges += 1  # bonus charge so this never eats a real one
        if self.player.fire_infinity_ray(self.beams, self.sounds, bypass_lock=True):
            self._resolve_infinity_ray_hits()
        self._buzz("infinity_ray")
        self._push_ai_toast("ULTIMATE UNLEASHED!", color=PURPLE)
        self.sounds.play("ultimate")
        self.telemetry.log_event("ultimate", layer=self.layer.name)
        if not self.secret_found:
            self.secret_found = True
            self._push_ai_toast("SECRET DISCOVERED: TILT + SHOUT ULTIMATE", color=YELLOW)
            self.sounds.play("secret_found")
            self._save_progress()

    def _update_playing(self, dt, keys):
        self.player.update(dt, keys)
        profile = self.player_profiles[self.layer]
        profile.observe_position(self.player.y, HEIGHT)
        profile.observe_aggression(self._current_aggression_signal())
        self._track_reaction_time(dt)
        self._update_sensor_mechanics(dt)
        self.telemetry.maybe_sample(dt, aggression=profile.avg_aggression(), accuracy=profile.accuracy(),
                                     wave=self.wave, layer=self.layer.name)
        if self.sounds.music:
            self.sounds.music.set_intensity(profile.avg_aggression())

        if keys[pygame.K_z] or keys[pygame.K_j]:  # A button
            fired = self.player.alive and self.player.nails_cooldown <= 0
            self.player.fire_nails(self.bullets, self.sounds)
            if fired:
                profile.observe_shot_fired("A")

        if self.player.alive:
            chaos_event = self.formation.update(dt, self.player, self.bullets, self.particles, self.sounds)
            if chaos_event:
                self._push_ai_toast(self.chaos_directors[self.layer].label_for(chaos_event), color=RED)
                self.sounds.play("chaos_event")
                self.telemetry.log_event("chaos_event", chaos_event=chaos_event)
            self._update_projectiles(dt)
            self._handle_collisions_wave()
        else:
            # player is dead: let projectiles/particles already in
            # flight finish naturally, but stop spawning new activity
            # (enemy dives/kills, friendly fire) so the particle count
            # can actually reach zero and DEFEAT can trigger.
            self._update_projectiles(dt)

        if self.player.alive and self.formation.cleared():
            self.state = GameState.WAVE_CLEAR
            self.state_timer = 1.8
            self.sounds.play("level_clear")
            self._save_progress()

        if not self.player.alive and len(self.particles) == 0:
            self.state = GameState.DEFEAT
            self.state_timer = 0.0
            self.sounds.play("game_over")
            self._buzz("defeat")
            self.telemetry.log_event("defeat", layer=self.layer.name, wave=self.wave, score=self.score)
            self._save_progress()

    def _update_boss_fight(self, dt, keys):
        self.player.update(dt, keys)
        profile = self.player_profiles[self.layer]
        profile.observe_position(self.player.y, HEIGHT)
        self._track_reaction_time(dt)
        self._update_sensor_mechanics(dt)
        self.telemetry.maybe_sample(dt, aggression=profile.avg_aggression(), accuracy=profile.accuracy(),
                                     wave="boss", layer=self.layer.name)

        if keys[pygame.K_z] or keys[pygame.K_j]:
            fired = self.player.alive and self.player.nails_cooldown <= 0
            self.player.fire_nails(self.bullets, self.sounds)
            if fired:
                profile.observe_shot_fired("A")

        max_phase = 0
        if self.player.alive:
            for boss in self.boss_group:
                if boss.alive and not boss.downed:
                    boss.update(dt, self.player, self.bullets, self.particles, self.sounds)
                    max_phase = max(max_phase, boss.phase)
                    if boss.pending_taunt:
                        self._push_ai_toast(boss.pending_taunt, color=RED)
                        boss.pending_taunt = None
                    if boss.just_changed_phase:
                        boss.just_changed_phase = False
                        self._buzz("boss_phase")
                        self._spawn_boss_adds(boss)

            for add in self.boss_adds:
                if add.alive:
                    add.update(dt, 0, self.player, self.bullets, self.sounds, ENEMY_BULLET_SPEED,
                               other_enemies=self.boss_adds)
            self.boss_adds = [a for a in self.boss_adds if a.alive]

            if self.sounds.music:
                self.sounds.music.set_intensity(max(profile.avg_aggression(), max_phase / 2.0))

            self._update_projectiles(dt)
            self._handle_collisions_boss(dt)
            self._handle_collisions_boss_adds()

            alive_bosses = [b for b in self.boss_group if b.alive and not b.downed]
            pending_regen = any(b in self.regen_pending for b in self.boss_group)
            if not alive_bosses and not pending_regen:
                self.add_score(sum(ENEMY_STATS[b.type]["score"] for b in self.boss_group), self.player.x, self.player.y, color=PURPLE)
                self.sounds.play("boss_defeat")
                self.boss_adds.clear()
                self.completed_layers.add(self.layer)
                self.telemetry.log_event("boss_defeated", layer=self.layer.name, score=self.score)
                self._save_progress()
                if len(self.completed_layers) >= len(Layer) and not self._campaign_announced:
                    self._campaign_announced = True
                    self.state = GameState.CAMPAIGN_COMPLETE
                    self.state_timer = 0.0
                else:
                    self.state = GameState.POST_BOSS_CHOICE
                    self.menu_cursor = 0
        else:
            self._update_projectiles(dt)

        if not self.player.alive and len(self.particles) == 0:
            self.state = GameState.DEFEAT
            self.state_timer = 0.0
            self.sounds.play("game_over")
            self._buzz("defeat")
            self.telemetry.log_event("defeat", layer=self.layer.name, wave="boss", score=self.score)
            self._save_progress()

    def _spawn_boss_adds(self, boss):
        """Enemy formation/swarm behavior that reacts to boss AI state:
        every time the boss crosses a phase threshold, it calls in a
        few of the layer's regular enemies as reinforcements -- not
        just the boss itself getting angrier, the whole encounter
        escalates."""
        if len([a for a in self.boss_adds if a.alive]) >= 6:
            return
        types = LAYER_ENEMY_TYPES.get(self.layer)
        if not types:
            return
        etype = types[0]
        count = 2 + boss.phase
        for i in range(count):
            side = "top" if i % 2 == 0 else "bottom"
            slot_x = WIDTH - 90 - (i % 3) * 40
            slot_y = HEIGHT * 0.18 + (i * 90) % (HEIGHT * 0.64)
            self.boss_adds.append(Enemy(etype, slot_x, slot_y, side, entry_delay=i * 0.15))
        self._push_ai_toast(f"{boss.display_name} SUMMONS REINFORCEMENTS!", color=RED)
        self.telemetry.log_event("boss_adds_spawned", layer=self.layer.name, phase=boss.phase)

    def _update_projectiles(self, dt):
        for b in self.bullets:
            b.update(dt)
        self.bullets = [b for b in self.bullets if b.alive]

        if self.player.mjolnir_active:
            self.player.mjolnir_active.update(dt, self.player)
            if not self.player.mjolnir_active.alive:
                self.player.mjolnir_active = None

        for bomb in self.bombs:
            bomb.update(dt)
        self.bombs = [bomb for bomb in self.bombs if bomb.alive]

        for beam in self.beams:
            beam.update(dt)
        self.beams = [b for b in self.beams if b.alive]

    # input actions (weapons B / X / Y are edge-triggered)
    def _fire_weapon_b(self):
        if self.state in (GameState.PLAYING, GameState.BOSS_FIGHT):
            fired = self.player.alive and self.player.mjolnir_cooldown <= 0 and self.player.mjolnir_active is None
            self.player.throw_mjolnir(self.sounds)
            if fired:
                self.player_profiles[self.layer].observe_shot_fired("B")

    def _fire_weapon_x(self):
        if self.state in (GameState.PLAYING, GameState.BOSS_FIGHT):
            if self.player.fire_infinity_ray(self.beams, self.sounds):
                self.player_profiles[self.layer].observe_weapon("X")
                self.player_profiles[self.layer].observe_shot_fired("X")
                self._buzz("infinity_ray")
                self._resolve_infinity_ray_hits()

    def _fire_weapon_y(self):
        if self.state in (GameState.PLAYING, GameState.BOSS_FIGHT):
            fired = self.player.alive and self.player.bomb_cooldown <= 0
            self.player.throw_bomb(self.bombs, self.sounds)
            if fired:
                self.player_profiles[self.layer].observe_shot_fired("Y")

    def _resolve_infinity_ray_hits(self):
        if not self.beams:
            return
        beam = self.beams[-1]
        beam_y = beam.y
        # regular enemies: always obliterated
        if self.formation:
            for e in self.formation.alive_enemies():
                if beam.rect().collidepoint(e.x, e.y) or abs(e.y - beam_y) < beam.width:
                    e.alive = False
                    self.player_profiles[self.layer].observe_shot_hit("X")
                    self.player_profiles[self.layer].record_kill("X")
                    multiplier = self.player.register_kill(e.state == EnemyState.DIVING)
                    self.add_score(int(e.score * multiplier), e.x, e.y, color=PURPLE)
                    spawn_explosion(self.particles, e.x, e.y, PURPLE)
        # bosses: may dodge
        for boss in self.boss_group:
            if not boss.alive or boss.downed:
                continue
            if abs(boss.y - beam_y) < beam.width * 1.5:
                dodged = boss.try_dodge_infinity_ray(beam_y)
                if not dodged:
                    dmg = int(boss.max_hp * 0.5)  # heavy but not always instant kill for bosses
                    if boss.regen:
                        dmg = boss.max_hp  # infinity ray damages regen-twins easily, per spec
                    boss.take_damage(dmg, "X")
                    self.player_profiles[self.layer].observe_shot_hit("X")
                    self.sounds.play("boss_hit")
                    self._trigger_impact_frame()
                    spawn_explosion(self.particles, boss.x, boss.y, PURPLE, count=14)
                    if boss.downed or not boss.alive:
                        self._on_boss_downed(boss)

    # collisions
    def _handle_collisions_wave(self):
        player_bullets = [b for b in self.bullets if b.is_player and b.alive]
        enemy_bullets = [b for b in self.bullets if not b.is_player and b.alive]

        for enemy in self.formation.alive_enemies():
            for b in player_bullets:
                if not b.alive:
                    continue
                if enemy.rect.collidepoint(b.x, b.y):
                    b.alive = False
                    enemy.hp -= b.damage
                    self.player_profiles[self.layer].observe_weapon("A")
                    self.player_profiles[self.layer].observe_shot_hit("A")
                    if enemy.hp <= 0:
                        self._kill_enemy(enemy, "A")
                    break

        # mjolnir hits
        if self.player.mjolnir_active:
            m = self.player.mjolnir_active
            for enemy in self.formation.alive_enemies():
                already = m.hit_enemies_back if m.returning else m.hit_enemies_out
                if id(enemy) in already:
                    continue
                if enemy.rect.colliderect(m.rect()):
                    enemy.hp -= m.damage
                    already.add(id(enemy))
                    self.player_profiles[self.layer].observe_weapon("B")
                    self.player_profiles[self.layer].observe_shot_hit("B")
                    if enemy.hp <= 0:
                        self._kill_enemy(enemy, "B")

        # bombs: detonate on contact with an enemy, then deal radius
        # damage to all enemies caught in the blast; never hurts the player
        for bomb in self.bombs:
            if bomb.exploded or not bomb.alive:
                continue
            for enemy in self.formation.alive_enemies():
                if enemy.rect.collidepoint(bomb.x, bomb.y):
                    bomb.detonate()
                    self.sounds.play("bomb_blast")
                    self._trigger_impact_frame()
                    self._buzz("explosion")
                    break
        for bomb in self.bombs:
            if bomb.exploded and bomb.explosion_timer >= bomb.explosion_max - 0.001:
                # just detonated this frame -- apply blast damage once
                for enemy in self.formation.alive_enemies():
                    dx, dy = enemy.x - bomb.x, enemy.y - bomb.y
                    if dx * dx + dy * dy <= bomb.blast_radius ** 2:
                        enemy.hp -= bomb.damage
                        self.player_profiles[self.layer].observe_weapon("Y")
                        self.player_profiles[self.layer].observe_shot_hit("Y")
                        if enemy.hp <= 0:
                            self._kill_enemy(enemy, "Y")

        if self.player.alive:
            for b in enemy_bullets:
                if not b.alive:
                    continue
                if self.player.rect.collidepoint(b.x, b.y):
                    b.alive = False
                    if self.player.hit(self.particles, self.sounds, amount=1):
                        self.player.break_combo()
                        self._trigger_impact_frame()
                elif not getattr(b, "_near_missed", False):
                    dx, dy = b.x - self.player.x, b.y - self.player.y
                    if dx * dx + dy * dy <= 34 ** 2:
                        b._near_missed = True
                        self._buzz("near_miss")

            for enemy in self.formation.alive_enemies():
                if enemy.state == EnemyState.DIVING and enemy.rect.colliderect(self.player.rect):
                    enemy.alive = False
                    spawn_explosion(self.particles, enemy.x, enemy.y, enemy.color)
                    dmg = 2 if enemy.melee_only else 1
                    if self.player.hit(self.particles, self.sounds, amount=dmg):
                        self.player.break_combo()
                        self._trigger_impact_frame()

        self.bullets = [b for b in self.bullets if b.alive]

    def _kill_enemy(self, enemy, weapon_letter=None):
        enemy.alive = False
        if weapon_letter is not None:
            self.player_profiles[self.layer].record_kill(weapon_letter)
        risky = enemy.state == EnemyState.DIVING
        if not risky and self.formation:
            for other in self.formation.alive_enemies():
                if other is not enemy and other.state == EnemyState.DIVING:
                    dx, dy = other.x - self.player.x, other.y - self.player.y
                    if dx * dx + dy * dy <= COMBO_RISK_RADIUS ** 2:
                        risky = True
                        break
        multiplier = self.player.register_kill(risky)
        base_points = enemy.dive_score if enemy.state == EnemyState.DIVING else enemy.score
        self.add_score(int(base_points * multiplier), enemy.x, enemy.y, color=enemy.color)
        if multiplier > 1.4:
            self.sounds.play("combo")
        spawn_explosion(self.particles, enemy.x, enemy.y, enemy.color)
        self.sounds.play("explosion")
        self._trigger_impact_frame()
        self._buzz("explosion")

    def _handle_collisions_boss(self, dt):
        player_bullets = [b for b in self.bullets if b.is_player and b.alive]
        enemy_bullets = [b for b in self.bullets if not b.is_player and b.alive]

        for boss in self.boss_group:
            if not boss.alive or boss.downed:
                continue
            for b in player_bullets:
                if not b.alive:
                    continue
                if boss.rect.collidepoint(b.x, b.y):
                    b.alive = False
                    boss.take_damage(b.damage, "A")
                    self.player_profiles[self.layer].observe_weapon("A")
                    self.player_profiles[self.layer].observe_shot_hit("A")
                    self.sounds.play("boss_hit")
                    self._trigger_impact_frame()
                    if boss.downed or not boss.alive:
                        self._on_boss_downed(boss)
                    break

            if self.player.mjolnir_active:
                m = self.player.mjolnir_active
                already = m.hit_enemies_back if m.returning else m.hit_enemies_out
                if id(boss) not in already and boss.rect.colliderect(m.rect()):
                    boss.take_damage(m.damage, "B")
                    already.add(id(boss))
                    self.player_profiles[self.layer].observe_weapon("B")
                    self.player_profiles[self.layer].observe_shot_hit("B")
                    self.sounds.play("boss_hit")
                    self._trigger_impact_frame()
                    if boss.downed or not boss.alive:
                        self._on_boss_downed(boss)

            for bomb in self.bombs:
                if bomb.alive and not bomb.exploded and boss.rect.colliderect(bomb.rect()):
                    bomb.detonate()
                    self.sounds.play("boss_hit")
                    self._trigger_impact_frame()
                    self._buzz("explosion")

            if (boss.charging or boss.charge_finished_this_frame) and boss.rect.colliderect(self.player.rect) and self.player.alive:
                if self.player.hit(self.particles, self.sounds, amount=boss.melee_damage()):
                    boss.learner.observe_hit_taken()
                    self.player.break_combo()
                    self._trigger_impact_frame()

        # regen tick for twin bosses: while a downed twin's partner is
        # still alive, count down; if time runs out, the downed twin
        # is fully revived (regenerates). If both go down in time, the
        # window is cleared elsewhere (see _on_boss_downed) and this
        # boss is left permanently dead.
        for boss, remaining in list(self.regen_pending.items()):
            remaining -= dt
            if remaining <= 0:
                if boss.downed:
                    boss.downed = False
                    boss.hp = max(1, int(boss.max_hp * REGEN_HEAL_FRACTION))
                    spawn_explosion(self.particles, boss.x, boss.y, GREEN, count=20)
                del self.regen_pending[boss]
            else:
                self.regen_pending[boss] = remaining

        # bomb blast damage against bosses -- applied once, on the frame
        # a bomb detonates, to every boss caught in the radius
        for bomb in self.bombs:
            if bomb.exploded and bomb.explosion_timer >= bomb.explosion_max - 0.001:
                for boss in self.boss_group:
                    if not boss.alive or boss.downed:
                        continue
                    dx, dy = boss.x - bomb.x, boss.y - bomb.y
                    if dx * dx + dy * dy <= bomb.blast_radius ** 2:
                        boss.take_damage(bomb.damage, "Y")
                        self.player_profiles[self.layer].observe_weapon("Y")
                        self.player_profiles[self.layer].observe_shot_hit("Y")
                        if boss.downed or not boss.alive:
                            self._on_boss_downed(boss)

        if self.player.alive:
            for b in enemy_bullets:
                if not b.alive:
                    continue
                if self.player.rect.collidepoint(b.x, b.y):
                    b.alive = False
                    if self.player.hit(self.particles, self.sounds, amount=1):
                        self.player.break_combo()
                        self._trigger_impact_frame()
                elif not getattr(b, "_near_missed", False):
                    dx, dy = b.x - self.player.x, b.y - self.player.y
                    if dx * dx + dy * dy <= 34 ** 2:
                        b._near_missed = True
                        self._buzz("near_miss")

        self.bullets = [b for b in self.bullets if b.alive]
        self.bombs = [bomb for bomb in self.bombs if bomb.alive]

    def _handle_collisions_boss_adds(self):
        """Collisions for the reinforcement enemies spawned by
        _spawn_boss_adds() -- same shape as _handle_collisions_wave
        but against self.boss_adds instead of a Formation."""
        if not self.boss_adds:
            return
        player_bullets = [b for b in self.bullets if b.is_player and b.alive]
        for add in self.boss_adds:
            if not add.alive:
                continue
            for b in player_bullets:
                if not b.alive:
                    continue
                if add.rect.collidepoint(b.x, b.y):
                    b.alive = False
                    add.hp -= b.damage
                    self.player_profiles[self.layer].observe_shot_hit("A")
                    if add.hp <= 0:
                        self._kill_enemy(add, "A")
                    break
            if self.player.mjolnir_active:
                m = self.player.mjolnir_active
                already = m.hit_enemies_back if m.returning else m.hit_enemies_out
                if id(add) not in already and add.rect.colliderect(m.rect()):
                    add.hp -= m.damage
                    already.add(id(add))
                    if add.hp <= 0:
                        self._kill_enemy(add, "B")
            if self.player.alive and add.state == EnemyState.DIVING and add.rect.colliderect(self.player.rect):
                add.alive = False
                spawn_explosion(self.particles, add.x, add.y, add.color)
                if self.player.hit(self.particles, self.sounds, amount=1):
                    self.player.break_combo()
                    self._trigger_impact_frame()
        self.bullets = [b for b in self.bullets if b.alive]

    def _on_boss_downed(self, boss):
        spawn_explosion(self.particles, boss.x, boss.y, boss.color, count=40, speed=260)
        self._buzz("explosion")
        if not boss.regen:
            return  # non-regen bosses just die, nothing more to do

        partners = [b for b in self.boss_group if b is not boss and b.regen]
        for partner in partners:
            if partner.downed:
                # partner was already downed and waiting -- both fell
                # within the window, so BOTH die permanently now.
                partner.alive = False
                partner.downed = False
                boss.alive = False
                boss.downed = False
                if partner in self.regen_pending:
                    del self.regen_pending[partner]
                if boss in self.regen_pending:
                    del self.regen_pending[boss]
            elif partner.alive:
                # partner still fighting -- start this boss's regen countdown
                self.regen_pending[boss] = REGEN_WINDOW

    # draw
    def draw(self):
        self.screen.fill(BLACK)
        self.starfield.draw(self.screen)

        if self.state == GameState.START:
            self._draw_start_screen()
        elif self.state == GameState.LAYER_SELECT:
            self._draw_layer_select()
        elif self.state == GameState.QUIT_CONFIRM:
            self._draw_quit_screen()
        elif self.state == GameState.DEFEAT:
            self._draw_defeat_screen()
        elif self.state == GameState.AI_REPORT_CARD:
            self._draw_report_card()
        elif self.state == GameState.ENTER_INITIALS:
            self._draw_enter_initials()
        elif self.state == GameState.LEADERBOARD:
            self._draw_leaderboard()
        elif self.state == GameState.CAMPAIGN_COMPLETE:
            self._draw_campaign_complete()
        else:
            draw_state = self._pre_pause_state if self.state == GameState.PAUSED else self.state

            if draw_state in (GameState.PLAYING, GameState.WAVE_CLEAR):
                if self.formation:
                    self.formation.draw(self.screen)
            if draw_state in (GameState.BOSS_INTRO, GameState.BOSS_FIGHT, GameState.POST_BOSS_CHOICE):
                for boss in self.boss_group:
                    boss.draw(self.screen)
                for add in self.boss_adds:
                    if add.alive:
                        add.draw(self.screen)

            for b in self.bullets:
                b.draw(self.screen)
            for bomb in self.bombs:
                bomb.draw(self.screen)
            for beam in self.beams:
                beam.draw(self.screen)
            self.player.draw(self.screen)
            for p in self.particles:
                p.draw(self.screen)
            for pop in self.popups:
                pop.draw(self.screen)
            for i, toast in enumerate(self.ai_toasts):
                toast.draw(self.screen, i)

            self._draw_hud()

            if draw_state == GameState.WAVE_CLEAR:
                draw_text(self.screen, f"WAVE {self.wave} CLEAR!", 28, GREEN, (WIDTH / 2, HEIGHT / 2), glow=True)
            elif draw_state == GameState.BOSS_INTRO:
                self._draw_boss_intro()
            elif draw_state == GameState.POST_BOSS_CHOICE:
                self._draw_post_boss_choice()

            if self.state == GameState.PAUSED:
                self._draw_pause_menu()

        self.screen.blit(self.scanlines, (0, 0))
        self._present()

    def _draw_start_screen(self):
        t = pygame.time.get_ticks() / 1000

        # CRT-green treatment: dim the starfield toward black, lay a
        # static green dither field on top, then the vignette.
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 4, 2, 215))
        self.screen.blit(dim, (0, 0))
        draw_dither_noise(self.screen, self._start_noise_cells, self._dither_cell, palette=CRT_STATIC_PALETTE)
        self.screen.blit(self._start_vignette, (0, 0))

        # split on the colon so the wordmark stays derived from
        # GAME_TITLE instead of a separately hardcoded string
        main_title, _, subtitle = GAME_TITLE.partition(":")
        subtitle = subtitle.strip()

        flicker = 210 + int(35 * abs(math.sin(t * 11)))  # irregular CRT flicker, not a clean pulse
        title_color = (30, flicker, 70)
        draw_pixel_title(self.screen, main_title, 58, title_color, (WIDTH / 2, HEIGHT * 0.24))
        draw_text(self.screen, subtitle, 16, (70, 200, 110), (WIDTH / 2, HEIGHT * 0.345))

        # Thin horizontal scan bar sweeping down over the logo, like a
        # CRT refresh line -- purely cosmetic, loops every ~2.2s.
        sweep_y = HEIGHT * 0.10 + (t % 2.2) / 2.2 * HEIGHT * 0.30
        bar = pygame.Surface((WIDTH, 3), pygame.SRCALPHA)
        bar.fill((120, 255, 170, 70))
        self.screen.blit(bar, (0, sweep_y))

        draw_sprite(self.screen, PLAYER_GRID, PLAYER_PALETTE, WIDTH / 2, HEIGHT * 0.52, PIXEL_SCALE * 2)

        if int(t * 2) % 2 == 0:
            draw_text(self.screen, "PRESS ENTER TO START", 20, (200, 255, 210), (WIDTH / 2, HEIGHT * 0.68), glow=True)
        draw_text(self.screen, "ARROWS/WASD MOVE   Z=A NAILS  X=B MJOLNIR  C=X RAY  V=Y BOMB", 12, (90, 170, 120), (WIDTH / 2, HEIGHT * 0.75))
        draw_text(self.screen, "ESC TO QUIT", 12, (60, 120, 85), (WIDTH / 2, HEIGHT * 0.80))
        if self.high_score > 0:
            draw_text(self.screen, f"HIGH SCORE {self.high_score}", 16, (80, 230, 140), (WIDTH / 2, HEIGHT * 0.88))

    def _draw_layer_select(self):
        draw_text(self.screen, "CHOOSE YOUR LAYER", 30, CYAN, (WIDTH / 2, HEIGHT * 0.14), glow=True)
        layers = list(Layer)
        for i, layer in enumerate(layers):
            y = HEIGHT * 0.32 + i * HEIGHT * 0.19
            selected = (i == self.menu_cursor)
            color = YELLOW if selected else WHITE
            prefix = "> " if selected else "  "
            draw_text(self.screen, prefix + LAYER_NAMES[layer], 20, color, (WIDTH / 2, y))
            draw_text(self.screen, LAYER_SUBTITLES[layer], 12, DIM_BLUE, (WIDTH / 2, y + 22))
        draw_text(self.screen, "UP/DOWN SELECT   ENTER CONFIRM   ESC QUIT", 13, WHITE, (WIDTH / 2, HEIGHT * 0.94))

    def _draw_boss_intro(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        self.screen.blit(overlay, (0, 0))
        names = " & ".join(BOSS_DISPLAY_NAMES.get(b.type.name, b.type.name.replace("_", " ")) for b in self.boss_group)
        draw_text(self.screen, "WARNING", 22, RED, (WIDTH / 2, HEIGHT * 0.38), glow=True)
        draw_text(self.screen, names, 34, WHITE, (WIDTH / 2, HEIGHT * 0.5), glow=True)
        for i, boss in enumerate(self.boss_group):
            x = WIDTH / 2 + (i - (len(self.boss_group) - 1) / 2) * 140
            grid, palette = BOSS_ART[boss.type.name]
            draw_sprite(self.screen, grid, palette, x, HEIGHT * 0.72, PIXEL_SCALE)

    def _draw_post_boss_choice(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))
        draw_text(self.screen, "LAYER CLEARED!", 30, GREEN, (WIDTH / 2, HEIGHT * 0.24), glow=True)
        draw_text(self.screen, f"SCORE {self.score}", 16, WHITE, (WIDTH / 2, HEIGHT * 0.32))

        options = ["CONTINUE THIS LAYER", "CHOOSE A DIFFERENT LAYER", "QUIT"]
        for i, label in enumerate(options):
            y = HEIGHT * 0.48 + i * 46
            selected = (i == self.menu_cursor)
            color = YELLOW if selected else WHITE
            prefix = "> " if selected else "  "
            draw_text(self.screen, prefix + label, 20, color, (WIDTH / 2, y))
        draw_text(self.screen, "UP/DOWN SELECT   ENTER CONFIRM", 13, DIM_BLUE, (WIDTH / 2, HEIGHT * 0.9))

    def _draw_pause_menu(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))
        draw_text(self.screen, "PAUSED", 30, CYAN, (WIDTH / 2, HEIGHT * 0.28), glow=True)

        options = ["RESUME", "RESTART LAYER", "QUIT"]
        for i, label in enumerate(options):
            y = HEIGHT * 0.48 + i * 46
            selected = (i == self.pause_cursor)
            color = YELLOW if selected else WHITE
            prefix = "> " if selected else "  "
            draw_text(self.screen, prefix + label, 20, color, (WIDTH / 2, y))
        draw_text(self.screen, "UP/DOWN SELECT   ENTER CONFIRM   P/ESC RESUME", 13, DIM_BLUE, (WIDTH / 2, HEIGHT * 0.9))

    def _draw_hud(self):
        draw_text(self.screen, f"SCORE {self.score:06d}", 15, WHITE, (100, 16))
        draw_text(self.screen, f"HI {self.high_score:06d}", 13, CYAN, (WIDTH / 2, 14))
        if self.state in (GameState.PLAYING, GameState.WAVE_CLEAR):
            draw_text(self.screen, f"WAVE {self.wave}/{WAVES_PER_LAYER}", 15, GREEN, (WIDTH - 90, 16))
        else:
            draw_text(self.screen, "BOSS FIGHT", 15, RED, (WIDTH - 90, 16))
        draw_text(self.screen, LAYER_NAMES[self.layer].split(":")[0], 11, DIM_BLUE, (WIDTH - 90, 32))

        if self.player.combo_count >= 2:
            draw_text(self.screen, f"COMBO x{self.player.combo_multiplier:.2f}", 14, ORANGE, (100, 34))
        if self.player.overcharge_ready:
            t = pygame.time.get_ticks() / 1000
            if int(t * 4) % 2 == 0:
                draw_text(self.screen, "OVERCHARGED!", 13, ORANGE, (WIDTH / 2, 30))

        for i in range(self.player.lives):
            self.player.draw_life_icon(self.screen, 24 + i * 26, HEIGHT - 16)

        draw_text(self.screen, f"RAY x{self.player.infinity_charges}", 13, PURPLE, (WIDTH - 60, HEIGHT - 16))

        if self.player.locked_weapon is not None:
            name = WEAPON_DISPLAY_NAMES.get(self.player.locked_weapon, self.player.locked_weapon)
            t = pygame.time.get_ticks() / 1000
            if int(t * 3) % 2 == 0:
                draw_text(self.screen, f"{name} LOCKED ({self.player.weapon_lock_waves_left})",
                          12, RED, (WIDTH / 2, HEIGHT - 16))

    def _draw_quit_screen(self):
        self.screen.fill(BLACK)
        draw_dither_noise(self.screen, self._dither_cells, self._dither_cell)
        draw_sprite(self.screen, QUIT_GLYPH_GRID, DITHER_PALETTE, WIDTH / 2, HEIGHT * 0.46, PIXEL_SCALE * 3)

        band = pygame.Surface((WIDTH, 74), pygame.SRCALPHA)
        band.fill((0, 0, 0, 190))
        self.screen.blit(band, (0, HEIGHT * 0.10 - 20))
        draw_text(self.screen, "SIGNAL LOST...", 26, (220, 220, 230), (WIDTH / 2, HEIGHT * 0.14), glow=True)

        band2 = pygame.Surface((WIDTH, 90), pygame.SRCALPHA)
        band2.fill((0, 0, 0, 190))
        self.screen.blit(band2, (0, HEIGHT * 0.82))
        draw_text(self.screen, "THANKS FOR RACING", 20, WHITE, (WIDTH / 2, HEIGHT * 0.85))
        draw_text(self.screen, f"FINAL SCORE {self.score}", 16, (170, 170, 180), (WIDTH / 2, HEIGHT * 0.91))
        t = pygame.time.get_ticks() / 1000
        if int(t * 2) % 2 == 0:
            draw_text(self.screen, "PRESS ENTER TO RETURN TO TITLE", 14, (235, 235, 240), (WIDTH / 2, HEIGHT * 0.97))

    def _draw_defeat_screen(self):
        self.screen.fill(BLACK)
        draw_dither_noise(self.screen, self._dither_cells, self._dither_cell)
        draw_sprite(self.screen, DEFEAT_GLYPH_GRID, DITHER_PALETTE, WIDTH / 2, HEIGHT * 0.42, PIXEL_SCALE * 3)

        band = pygame.Surface((WIDTH, 100), pygame.SRCALPHA)
        band.fill((0, 0, 0, 185))
        self.screen.blit(band, (0, HEIGHT * 0.02))
        draw_text(self.screen, "DEFEATED", 40, (230, 230, 235), (WIDTH / 2, HEIGHT * 0.12), glow=True)

        band2 = pygame.Surface((WIDTH, 110), pygame.SRCALPHA)
        band2.fill((0, 0, 0, 185))
        self.screen.blit(band2, (0, HEIGHT * 0.80))
        draw_text(self.screen, f"FINAL SCORE {self.score}", 18, WHITE, (WIDTH / 2, HEIGHT * 0.85))
        t = pygame.time.get_ticks() / 1000
        if int(t * 2) % 2 == 0:
            draw_text(self.screen, "PRESS ENTER TO RESTART", 18, (230, 230, 235), (WIDTH / 2, HEIGHT * 0.92))
        draw_text(self.screen, "ESC FOR TITLE", 14, (150, 150, 160), (WIDTH / 2, HEIGHT * 0.97))

    def _draw_enter_initials(self):
        """Arcade-style 3-letter initials entry for the local top-5
        leaderboard, shown when a run's score makes the cut."""
        self.screen.fill(BLACK)
        draw_text(self.screen, "NEW HIGH SCORE!", 28, YELLOW, (WIDTH / 2, HEIGHT * 0.24), glow=True)
        draw_text(self.screen, f"SCORE {self.score}", 16, WHITE, (WIDTH / 2, HEIGHT * 0.32))
        draw_text(self.screen, "ENTER YOUR INITIALS", 14, DIM_BLUE, (WIDTH / 2, HEIGHT * 0.42))

        letters = [INITIALS_CHARSET[i] for i in self.initials_indices]
        spacing = 56
        start_x = WIDTH / 2 - spacing
        for i, letter in enumerate(letters):
            x = start_x + i * spacing
            selected = (i == self.initials_cursor)
            color = YELLOW if selected else WHITE
            if selected:
                pygame.draw.rect(self.screen, DIM_BLUE, (x - 22, HEIGHT * 0.54 - 26, 44, 52), width=2)
            draw_text(self.screen, letter, 34, color, (x, HEIGHT * 0.54), glow=selected)
        draw_text(self.screen, "UP/DOWN CHANGE   LEFT/RIGHT MOVE   ENTER CONFIRM", 13, DIM_BLUE, (WIDTH / 2, HEIGHT * 0.9))

    def _draw_report_card(self):
        """Post-run "AI report card": a visual summary of what the
        adaptive AI learned about the player this run."""
        data = self.report_card_data or self._build_report_card()
        self.screen.fill(BLACK)
        draw_text(self.screen, "AI REPORT CARD", 28, CYAN, (WIDTH / 2, HEIGHT * 0.09), glow=True)
        draw_text(self.screen, data["layer"], 13, DIM_BLUE, (WIDTH / 2, HEIGHT * 0.15))

        draw_text(self.screen, f'PLAY STYLE: {data["play_style"]}', 18, YELLOW, (WIDTH / 2, HEIGHT * 0.23))
        draw_text(self.screen, f'FAVORITE WEAPON: {data["favorite_weapon"]}', 14, WHITE, (WIDTH / 2, HEIGHT * 0.29))

        bars = [
            ("AGGRESSION", data["aggression"], RED),
            ("ACCURACY", data["accuracy"], GREEN),
            ("RISK TOLERANCE", data["risk_tolerance"], ORANGE),
        ]
        bar_w = WIDTH * 0.6
        bar_x = WIDTH / 2 - bar_w / 2
        for i, (label, value, color) in enumerate(bars):
            y = HEIGHT * 0.40 + i * 46
            draw_text(self.screen, label, 12, DIM_BLUE, (bar_x, y - 12))
            pygame.draw.rect(self.screen, (40, 40, 50), (bar_x, y, bar_w, 10))
            pygame.draw.rect(self.screen, color, (bar_x, y, bar_w * max(0.02, min(1, value)), 10))

        draw_text(self.screen, f'AVG REACTION TIME: {data["reaction_time"]:.2f}s', 13, WHITE, (WIDTH / 2, HEIGHT * 0.62))
        if data["secret_found"]:
            draw_text(self.screen, "SECRET DISCOVERED: TILT + SHOUT ULTIMATE", 12, YELLOW, (WIDTH / 2, HEIGHT * 0.68))
        draw_text(self.screen, f'{data["samples"]} DATA POINTS OBSERVED THIS RUN', 11, DIM_BLUE, (WIDTH / 2, HEIGHT * 0.74))

        t = pygame.time.get_ticks() / 1000
        if int(t * 2) % 2 == 0:
            draw_text(self.screen, "PRESS ENTER TO CONTINUE", 16, WHITE, (WIDTH / 2, HEIGHT * 0.94))

    def _build_report_card(self):
        profile = self.player_profiles[self.layer]
        result = self.ei_classifier.classify(profile.feature_vector())
        return {
            "layer": LAYER_NAMES[self.layer],
            "favorite_weapon": WEAPON_DISPLAY_NAMES.get(profile.favorite_weapon(), profile.favorite_weapon()),
            "aggression": profile.avg_aggression(),
            "accuracy": profile.accuracy(),
            "reaction_time": profile.avg_reaction_time(),
            "risk_tolerance": profile.risk_tolerance(),
            "play_style": result.label.replace("_", " "),
            "samples": profile.samples,
            "score": self.score,
            "secret_found": self.secret_found,
        }

    def _draw_leaderboard(self):
        self.screen.fill(BLACK)
        draw_text(self.screen, "LOCAL LEADERBOARD", 28, CYAN, (WIDTH / 2, HEIGHT * 0.1), glow=True)
        if not self.leaderboard:
            draw_text(self.screen, "NO SCORES YET", 16, DIM_BLUE, (WIDTH / 2, HEIGHT * 0.4))
        for i, entry in enumerate(self.leaderboard[:LEADERBOARD_SIZE]):
            y = HEIGHT * 0.26 + i * 46
            color = YELLOW if i == 0 else WHITE
            draw_text(self.screen, f'{i + 1}. {entry.get("initials", "---")}   {entry.get("score", 0):06d}',
                      20, color, (WIDTH / 2, y))
            draw_text(self.screen, entry.get("layer", ""), 11, DIM_BLUE, (WIDTH / 2, y + 18))
        t = pygame.time.get_ticks() / 1000
        if int(t * 2) % 2 == 0:
            draw_text(self.screen, "PRESS ENTER TO CONTINUE", 16, WHITE, (WIDTH / 2, HEIGHT * 0.94))

    def _draw_campaign_complete(self):
        self.screen.fill(BLACK)
        draw_dither_noise(self.screen, self._dither_cells, self._dither_cell)
        draw_text(self.screen, "GALAXY SAVED", 40, YELLOW, (WIDTH / 2, HEIGHT * 0.32), glow=True)
        draw_text(self.screen, "ALL THREE LAYERS CLEARED IN ONE RUN", 16, WHITE, (WIDTH / 2, HEIGHT * 0.44))
        draw_text(self.screen, f"FINAL SCORE {self.score}", 18, CYAN, (WIDTH / 2, HEIGHT * 0.54))
        t = pygame.time.get_ticks() / 1000
        if int(t * 2) % 2 == 0:
            draw_text(self.screen, "PRESS ENTER TO CONTINUE", 16, WHITE, (WIDTH / 2, HEIGHT * 0.9))

    # input / event handling
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN:
            self._handle_keydown(event.key)

    def _handle_keydown(self, key):
        if key == pygame.K_p:
            if self.state in (GameState.PLAYING, GameState.BOSS_FIGHT):
                # Pause: remember where we were, freeze, open pause menu.
                self._pre_pause_state = self.state
                self.state = GameState.PAUSED
                self.pause_cursor = 0
                self.sounds.play("menu_select")
            elif self.state == GameState.PAUSED:
                self._unpause()
            return

        if key == pygame.K_ESCAPE:
            if self.state in (GameState.PLAYING, GameState.BOSS_FIGHT, GameState.LAYER_SELECT,
                               GameState.WAVE_CLEAR, GameState.BOSS_INTRO, GameState.POST_BOSS_CHOICE):
                self.state = GameState.QUIT_CONFIRM
                self.sounds.play("quit")
            elif self.state == GameState.QUIT_CONFIRM:
                self.running = False
            elif self.state == GameState.PAUSED:
                self._unpause()
            elif self.state == GameState.DEFEAT:
                # Bail to the title screen instead of forcing a
                # LAYER_SELECT restart (that's what Enter does here).
                self.state = GameState.START
                self.sounds.play("menu_select")
            elif self.state in (GameState.AI_REPORT_CARD, GameState.ENTER_INITIALS,
                                 GameState.LEADERBOARD, GameState.CAMPAIGN_COMPLETE):
                # Skip straight past the post-run screens to the title
                # rather than quitting the app outright.
                self.state = GameState.START
                self.sounds.play("menu_select")
            else:
                self.running = False
            return

        if self.state == GameState.PAUSED:
            options = ["RESUME", "RESTART LAYER", "QUIT"]
            if key in (pygame.K_UP, pygame.K_w):
                self.pause_cursor = (self.pause_cursor - 1) % len(options)
                self.sounds.play("menu_select")
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.pause_cursor = (self.pause_cursor + 1) % len(options)
                self.sounds.play("menu_select")
            elif key == pygame.K_RETURN:
                self._resolve_pause_choice()
            return

        if self.state == GameState.START:
            if key == pygame.K_RETURN:
                self.start_new_game()
                self.sounds.play("menu_select")
            elif key in (pygame.K_1, pygame.K_2, pygame.K_3):
                idx = (pygame.K_1, pygame.K_2, pygame.K_3).index(key)
                layers = list(Layer)
                if idx < len(layers):
                    self.start_new_game()
                    self.choose_layer(layers[idx], fresh_player=True)
                    self.sounds.play("menu_select")

        elif self.state == GameState.LAYER_SELECT:
            layers = list(Layer)
            if key in (pygame.K_UP, pygame.K_w):
                self.menu_cursor = (self.menu_cursor - 1) % len(layers)
                self.sounds.play("menu_select")
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.menu_cursor = (self.menu_cursor + 1) % len(layers)
                self.sounds.play("menu_select")
            elif key == pygame.K_RETURN:
                self.choose_layer(layers[self.menu_cursor])
                self.sounds.play("menu_select")
            elif key in (pygame.K_1, pygame.K_2, pygame.K_3):
                idx = (pygame.K_1, pygame.K_2, pygame.K_3).index(key)
                if idx < len(layers):
                    self.menu_cursor = idx
                    self.choose_layer(layers[idx])
                    self.sounds.play("menu_select")

        elif self.state in (GameState.PLAYING, GameState.BOSS_FIGHT):
            if key in (pygame.K_x, pygame.K_k):
                self._fire_weapon_b()
            elif key in (pygame.K_c, pygame.K_l):
                self._fire_weapon_x()
            elif key in (pygame.K_v, pygame.K_i):
                self._fire_weapon_y()

        elif self.state == GameState.POST_BOSS_CHOICE:
            if key in (pygame.K_UP, pygame.K_w):
                self.menu_cursor = (self.menu_cursor - 1) % 3
                self.sounds.play("menu_select")
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.menu_cursor = (self.menu_cursor + 1) % 3
                self.sounds.play("menu_select")
            elif key == pygame.K_RETURN:
                self._resolve_post_boss_choice()

        elif self.state == GameState.QUIT_CONFIRM:
            if key == pygame.K_RETURN:
                self.state = GameState.START

        elif self.state == GameState.DEFEAT:
            if key == pygame.K_RETURN:
                self._begin_post_run_flow()

        elif self.state == GameState.ENTER_INITIALS:
            charset = INITIALS_CHARSET
            if key in (pygame.K_UP, pygame.K_w):
                idx = self.initials_indices[self.initials_cursor]
                self.initials_indices[self.initials_cursor] = (idx - 1) % len(charset)
                self.sounds.play("menu_select")
            elif key in (pygame.K_DOWN, pygame.K_s):
                idx = self.initials_indices[self.initials_cursor]
                self.initials_indices[self.initials_cursor] = (idx + 1) % len(charset)
                self.sounds.play("menu_select")
            elif key in (pygame.K_LEFT, pygame.K_a):
                self.initials_cursor = max(0, self.initials_cursor - 1)
                self.sounds.play("menu_select")
            elif key in (pygame.K_RIGHT, pygame.K_d):
                self.initials_cursor = min(2, self.initials_cursor + 1)
                self.sounds.play("menu_select")
            elif key == pygame.K_RETURN:
                if self.initials_cursor < 2:
                    self.initials_cursor += 1
                    self.sounds.play("menu_select")
                else:
                    initials = "".join(charset[i] for i in self.initials_indices)
                    self.leaderboard = persistence.submit_leaderboard_score(
                        self.leaderboard, initials, self.score, LAYER_NAMES[self.layer], LEADERBOARD_SIZE)
                    self.sounds.play("leaderboard_entry")
                    self._save_progress()
                    self.state = GameState.AI_REPORT_CARD

        elif self.state == GameState.AI_REPORT_CARD:
            if key == pygame.K_RETURN:
                self.state = GameState.LEADERBOARD

        elif self.state == GameState.LEADERBOARD:
            if key == pygame.K_RETURN:
                self.state = GameState.START

        elif self.state == GameState.CAMPAIGN_COMPLETE:
            if key == pygame.K_RETURN:
                self.state = GameState.POST_BOSS_CHOICE
                self.menu_cursor = 0

    def _begin_post_run_flow(self):
        """DEFEAT -> either straight to the AI report card, or via the
        arcade-style initials entry first if the score makes the local
        top-5 leaderboard."""
        self.report_card_data = self._build_report_card()
        if persistence.qualifies_for_leaderboard(self.leaderboard, self.score, LEADERBOARD_SIZE):
            self.initials_indices = [0, 0, 0]
            self.initials_cursor = 0
            self.state = GameState.ENTER_INITIALS
        else:
            self.state = GameState.AI_REPORT_CARD

    def _unpause(self):
        self.sounds.play("menu_select")
        self.state = self._pre_pause_state or GameState.PLAYING
        self._pre_pause_state = None

    def _resolve_pause_choice(self):
        self.sounds.play("menu_select")
        if self.pause_cursor == 0:
            self._unpause()
        elif self.pause_cursor == 1:
            # Restart current layer from wave 1.
            self._pre_pause_state = None
            self.choose_layer(self.layer, fresh_player=True)
        else:
            self._pre_pause_state = None
            self.state = GameState.QUIT_CONFIRM
            self.sounds.play("quit")

    def _resolve_post_boss_choice(self):
        self.sounds.play("menu_select")
        if self.menu_cursor == 0:
            # continue same layer, loop back to wave 1 at higher difficulty pressure
            self.wave = 0
            self.player.reset_for_layer()
            self.next_wave()
        elif self.menu_cursor == 1:
            self.state = GameState.LAYER_SELECT
            self.menu_cursor = 0
        else:
            self._save_progress()
            self.state = GameState.QUIT_CONFIRM
            self.sounds.play("quit")

    # main loop
    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            dt = min(dt, 0.05)  # avoid huge jumps if the window is dragged/paused

            events = pygame.event.get()
            for event in events:
                self.handle_event(event)

            keys = pygame.key.get_pressed()
            self.update(dt, keys, events)
            self.draw()

        self._save_progress()
        pygame.quit()
