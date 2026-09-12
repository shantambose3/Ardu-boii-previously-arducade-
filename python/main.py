"""
Cyber Deck -- UNO Q Python (MPU/Linux) side entry point.

Polls controller state from sketch/sketch.ino via the Arduino_RouterBridge
(Bridge.call("get_controller_state"), once per frame -- the Bridge is
request/response only), translates button/joystick state into synthetic
pygame key events, and runs the Galactic Raiders game unchanged -- game.py
still just reads pygame.key.get_pressed() and KEYDOWN/KEYUP events.

Every frame this module also pushes an AI-status snapshot back to the
sketch (Bridge.call("set_ai_status", ...)), which the sketch renders on
the OLED, and drains queued haptic buzzes for the D6/D7 vibration motors
via HapticsBridge.

Field/bit layout sent over the Bridge (must match sketch/sketch.ino):
    buttons        bit0=D2, bit1=D3, bit2=D4, bit3=D5
    layerButtons   bit0=D8, bit1=D9, bit2=D10 -- sent but NOT acted on
                   here anymore (see key mapping note below); D8/D9/D10
                   only page/confirm the sketch's OLED instructions
                   guide now, not a Python-side layer jump.
    joyX, joyY     int, A0/A1 analog joystick
    lightLevel     int, A2 photoresistor -- eases wave difficulty in dim
                   rooms, see get_fatigue_level() below
    micLevel       int, A3 MAX9814 analog mic envelope
    accelX/Y/Z, mpuOk  MPU6050 (GY-521) raw accel + presence flag --
                   feeds motion_intensity (aggression signal), tilt
                   (dodge-roll / ultimate), and shake (panic bomb)

Key mapping:
    D2 -> V (bomb) AND Enter (menu confirm)
    D3 -> C (infinity ray) AND Escape (menu back)
    D4 -> Z (held, vacuum nails)
    D5 -> X (mjolnir)
    D8/D9/D10 -> OLED instructions guide only (page/confirm on the
                 sketch side); no longer an instant layer-jump on the
                 Python side. Use the joystick + confirm to pick a
                 layer, same as any other menu.
    Joystick -> W/A/S/D (movement and menu nav)
    D12 (sleepWake) -> P (pause/play) on a single tap; a second tap
                   within DOUBLE_TAP_WINDOW instead toggles the OLED's
                   "hide stats" setting (see _toggle_oled_stats()).

Sensor-mapped mechanics added on top of the above (all read via
ControllerBridge.get_tilt()/get_shake_intensity()/get_mic_intensity()
and handled game-side in Game._update_sensor_mechanics(), not here):
    MPU6050 tilt         -> dodge-roll / bank mechanic
    MPU6050 shake        -> screen-clear "panic bomb"
    MAX9814 sustained shout -> next-shot weapon overcharge
    tilt + shout together   -> rare "ultimate" (also the game's secret)

D2/D3 only send their menu equivalent while the game is actually showing
a menu (see _in_menu_state()) -- otherwise Escape's always-active global
handler in game.py would pop the quit-confirm screen on every infinity
ray shot.

Adjust BUTTON_KEY_MAP if your physical button wiring differs from
D2/D3/D4/D5.

Edge Impulse (game/edge_impulse.py) defaults to a rule-based stub with
the same interface as a real exported model; set the EI_BACKEND=eim
environment variable once a real .eim/Python model is wired up there.
"""

import sys
import os
import threading
import time

from arduino.app_utils import App, Bridge

GAME_DIR = os.path.join(os.path.dirname(__file__), "galactic_raiders")
sys.path.insert(0, GAME_DIR)

import pygame  # noqa: E402


BUTTON_KEY_MAP = {
    0: pygame.K_v,       # D2 -> bomb
    1: pygame.K_c,       # D3 -> infinity ray
    2: pygame.K_z,       # D4 -> vacuum nails (held)
    3: pygame.K_x,       # D5 -> mjolnir
}
BUTTON_HELD_KEYS = {pygame.K_z}  # keys that should be held, not tapped

MENU_KEY_MAP = {
    0: pygame.K_RETURN,  # D2 -> menu confirm / enter
    1: pygame.K_ESCAPE,  # D3 -> menu back / quit-confirm
}

JOY_DEADZONE = 80  # tune to your joystick module's center noise

# --- pygame.key.get_pressed() patch -----------------------------------
# pygame.event.post() pushes events onto the queue, and code reading
# discrete KEYDOWN events (menu navigation in game.py's handle_event())
# sees them fine. But pygame.key.get_pressed() reads SDL's own internal
# keyboard-state buffer, which is only updated by REAL hardware/OS key
# events -- posted synthetic events never touch it. Since player.py's
# movement (WASD) and the held vacuum-nails key (Z) both read via
# get_pressed(), they'd silently never respond to our synthetic events
# without this patch. We track our own "currently down" set and OR it
# into whatever get_pressed() would otherwise return.
_synthetic_keys_down = set()
_real_get_pressed = pygame.key.get_pressed


class _MergedKeyState:
    __slots__ = ("_real",)

    def __init__(self, real):
        self._real = real

    def __getitem__(self, key):
        return bool(self._real[key]) or key in _synthetic_keys_down


def _patched_get_pressed():
    return _MergedKeyState(_real_get_pressed())


pygame.key.get_pressed = _patched_get_pressed
# ------------------------------------------------------------------


class ControllerBridge:
    """Owns the connection to the MCU-side controller state and turns it
    into synthetic pygame events. poll() must be called once per frame
    since the Bridge is request/response only."""

    def __init__(self, game=None):
        self._lock = threading.Lock()
        self._last_buttons = 0
        self._last_sleep_wake = False
        self._last_joy_left = False
        self._last_joy_right = False
        self._last_joy_up = False
        self._last_joy_down = False
        self.latest_accel = (0, 0, 0)
        self._last_accel_mag = None
        self.latest_light_level = 0
        self.latest_mic_level = 0
        self.mpu_ok = False
        self._running = False
        self.game = game  # set after Game() is constructed

        # sleep/wake double-tap detection for the OLED-stats-hidden toggle
        self._sleep_wake_tap_times = []
        self.DOUBLE_TAP_WINDOW = 0.5  # seconds

    def start(self):
        self._running = True
        return self

    def poll(self):
        if not self._running:
            return
        try:
            rpc = Bridge.call("get_controller_state")
            data = rpc.result() if hasattr(rpc, "result") else rpc
        except Exception:
            return  # MCU not ready / call failed -- skip this frame
        if not data:
            return
        self._on_update(data)

    def _on_update(self, data):
        with self._lock:
            self._handle_buttons(data.get("buttons", 0))
            # layerButtons (D8/D9/D10) is deliberately not handled here --
            # see the removed _handle_layer_buttons()/LAYER_BUTTON_MAP note
            # in CHANGELOG.md. Those three buttons only page/confirm the
            # sketch's boot-time OLED instructions guide now; they no
            # longer instant-jump to a layer. Layer choice is joystick
            # up/down + confirm (or the 1/2/3 keyboard shortcuts in
            # game.py, for desktop dev).
            self._handle_sleep_wake(bool(data.get("sleepWake", False)))
            self._handle_joystick(data.get("joyX", 0), data.get("joyY", 0))
            self.latest_light_level = data.get("lightLevel", 0)
            self.latest_mic_level = data.get("micLevel", 0)
            self.latest_accel = (
                data.get("accelX", 0),
                data.get("accelY", 0),
                data.get("accelZ", 0),
            )
            self.mpu_ok = bool(data.get("mpuOk", False))

    def _post(self, key, down):
        event_type = pygame.KEYDOWN if down else pygame.KEYUP
        pygame.event.post(pygame.event.Event(event_type, key=key, mod=0))
        if down:
            _synthetic_keys_down.add(key)
        else:
            _synthetic_keys_down.discard(key)

    def _handle_buttons(self, buttons):
        for bit, key in BUTTON_KEY_MAP.items():
            was = bool(self._last_buttons & (1 << bit))
            now = bool(buttons & (1 << bit))
            if now == was:
                continue
            if key in BUTTON_HELD_KEYS:
                self._post(key, now)  # held key: mirror press/release
            elif now:
                self._post(key, True)   # tap key: KEYDOWN on press edge only
                self._post(key, False)

            if now and bit in MENU_KEY_MAP and self._in_menu_state():
                menu_key = MENU_KEY_MAP[bit]
                self._post(menu_key, True)
                self._post(menu_key, False)
        self._last_buttons = buttons

    def _in_menu_state(self):
        """True while a menu/overlay screen is showing, where Enter/Escape
        should act as confirm/back rather than firing weapons."""
        if self.game is None:
            return False
        from game.constants import GameState
        return self.game.state not in (GameState.PLAYING, GameState.BOSS_FIGHT)

    def _handle_sleep_wake(self, sleep_wake):
        """Single tap (falling->rising edge) posts K_p to toggle pause,
        same as before. A second tap within DOUBLE_TAP_WINDOW instead
        toggles "hide OLED stats" -- consumed here rather than also
        firing the single-tap pause action, so a double-tap doesn't
        also pause/unpause twice."""
        now = sleep_wake
        was = self._last_sleep_wake
        self._last_sleep_wake = now
        if not (now and not was):
            return
        t = time.monotonic()
        self._sleep_wake_tap_times = [x for x in self._sleep_wake_tap_times if t - x < self.DOUBLE_TAP_WINDOW]
        self._sleep_wake_tap_times.append(t)
        if len(self._sleep_wake_tap_times) >= 2:
            self._sleep_wake_tap_times.clear()
            self._toggle_oled_stats()
        else:
            self._post(pygame.K_p, True)
            self._post(pygame.K_p, False)

    def _toggle_oled_stats(self):
        if self.game is None:
            return
        try:
            self.game.oled_stats_hidden = not self.game.oled_stats_hidden
            self.game._save_progress()
            Bridge.call("set_oled_visibility", not self.game.oled_stats_hidden)
        except Exception:
            pass

    def _handle_joystick(self, joy_x, joy_y):
        want_left = joy_x < -JOY_DEADZONE
        want_right = joy_x > JOY_DEADZONE
        want_up = joy_y < -JOY_DEADZONE  # flip sign if inverted on your wiring
        want_down = joy_y > JOY_DEADZONE

        if want_left != self._last_joy_left:
            self._post(pygame.K_a, want_left)
            self._last_joy_left = want_left
        if want_right != self._last_joy_right:
            self._post(pygame.K_d, want_right)
            self._last_joy_right = want_right
        if want_up != self._last_joy_up:
            self._post(pygame.K_w, want_up)
            self._last_joy_up = want_up
        if want_down != self._last_joy_down:
            self._post(pygame.K_s, want_down)
            self._last_joy_down = want_down

    def get_motion_intensity(self):
        """0..1 normalized motion signal, or None if the GY-521 isn't
        reporting."""
        if not self.mpu_ok:
            return None
        ax, ay, az = self.latest_accel
        magnitude = (ax * ax + ay * ay + az * az) ** 0.5
        return min(1.0, magnitude / 20000.0)  # retune after real testing

    def get_tilt(self):
        """(tiltX, tiltY), each roughly -1..1, or None if the GY-521
        isn't reporting. Used for the tilt dodge-roll / bank mechanic
        and the tilt+shout compound "ultimate". Derived from raw
        accelX/accelY; TILT_SCALE is a rough starting point for the
        board flat-ish in hand -- retune against your actual wiring
        orientation once you can test on hardware."""
        if not self.mpu_ok:
            return None
        ax, ay, _ = self.latest_accel
        TILT_SCALE = 9000.0
        return (max(-1.0, min(1.0, ax / TILT_SCALE)), max(-1.0, min(1.0, ay / TILT_SCALE)))

    def get_shake_intensity(self):
        """0..1 "jerk" signal: how fast the acceleration magnitude is
        changing frame-to-frame, distinct from get_motion_intensity()'s
        raw magnitude -- a hard shake produces a spike in jerk even if
        the sensor settles back near a normal magnitude between reads.
        Used for the shake-to-panic-bomb mechanic."""
        if not self.mpu_ok:
            return None
        ax, ay, az = self.latest_accel
        mag = (ax * ax + ay * ay + az * az) ** 0.5
        jerk = abs(mag - self._last_accel_mag) if self._last_accel_mag is not None else 0.0
        self._last_accel_mag = mag
        SHAKE_SCALE = 6000.0  # retune after real testing
        return max(0.0, min(1.0, jerk / SHAKE_SCALE))

    def get_mic_intensity(self):
        """0..1 normalized loudness from the MAX9814 mic envelope on A3."""
        MIC_NOISE_FLOOR = 40    # raw ADC value with no sound (retune)
        MIC_CEILING = 700       # raw ADC value at "loud" (retune)
        raw = self.latest_mic_level
        span = max(1, MIC_CEILING - MIC_NOISE_FLOOR)
        return max(0.0, min(1.0, (raw - MIC_NOISE_FLOOR) / span))

    def get_fatigue_level(self):
        """0..1 "player looks tired" signal from the A2 photoresistor: a
        dimmer room eases wave difficulty (never boss fights, and only
        up to FATIGUE_EASE_CAP_PCT)."""
        PHOTO_DARK = 150     # raw ADC value in a dim/dark room (retune)
        PHOTO_BRIGHT = 700   # raw ADC value in a well-lit room (retune)
        raw = self.latest_light_level
        span = max(1, PHOTO_BRIGHT - PHOTO_DARK)
        fatigue = (PHOTO_BRIGHT - raw) / span  # darker -> higher fatigue
        return max(0.0, min(1.0, fatigue))

    def push_ai_status(self):
        """Call once per frame. Reads the live PlayerProfile off
        self.game and pushes a snapshot to the sketch for the OLED."""
        if self.game is None:
            return
        try:
            profile = self.game.player_profiles.get(self.game.layer)
            if profile is None:
                return

            LEARNING_SAMPLE_CAP = 150
            learning_pct = int(min(100, profile.samples / LEARNING_SAMPLE_CAP * 100))
            has_data = profile.samples > 0

            fatigue = self.get_fatigue_level()
            FATIGUE_EASE_CAP_PCT = 35
            fatigue_ease_pct = int(fatigue * FATIGUE_EASE_CAP_PCT)

            # Positional args, matching setAiStatus()'s plain-parameter
            # signature in sketch.ino -- RPClite's incoming-argument
            # deserializer doesn't accept a dict/struct as a single
            # argument, only primitives/strings/arrays/maps.
            Bridge.call(
                "set_ai_status",
                learning_pct,
                min(profile.samples, 65535),
                profile.favorite_weapon() if has_data else "-",
                int(profile.avg_aggression() * 100),
                fatigue_ease_pct,
            )
        except Exception:
            pass  # skip this frame rather than crash the loop over a Bridge hiccup


class HapticsBridge:
    """Fire-and-forget haptic buzz requests for the D6/D7 vibration
    motors. buzz() (called from game.py on the pygame thread) just
    queues timed steps; tick() (called from the bridge thread) sends
    them via Bridge.call("trigger_vibration", ...), so bursts of game
    events never block the render loop."""

    # event -> (list of (motor, duration_ms, delay_before_ms), min_interval_s)
    # min_interval_s rate-limits an event kind so e.g. a nails massacre
    # doesn't turn "explosion" into one continuous motor hum.
    PATTERNS = {
        "explosion":    ([("B", 70, 0)], 0.08),
        "infinity_ray": ([("B", 180, 0)], 0.3),
        "defeat":       ([("B", 220, 0), ("B", 220, 260)], 1.0),
        # -- software update additions -- motor is "L"/"R"/"B" (left/
        # right/both), matching triggerVibration()'s motor char in
        # sketch.ino -- NOT the weapon-slot letters used elsewhere.
        "dodge":        ([("L", 40, 0)], 0.15),
        "near_miss":    ([("R", 30, 0)], 0.35),   # short, subtle -- fires often
        "boss_phase":   ([("L", 120, 0), ("R", 120, 60)], 1.0),  # both motors, unmistakable
        "low_health":   ([("R", 90, 0)], 1.9),    # slow repeating pulse while at 1 life
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._queue = []  # sorted list of (send_at_monotonic, motor, duration_ms)
        self._last_fired = {}

    def buzz(self, event):
        spec = self.PATTERNS.get(event)
        if not spec:
            return
        pulses, min_interval = spec
        now = time.monotonic()
        with self._lock:
            last = self._last_fired.get(event, -1e9)
            if now - last < min_interval:
                return
            self._last_fired[event] = now
            t = now
            for motor, duration_ms, delay_before_ms in pulses:
                t += delay_before_ms / 1000.0
                self._queue.append((t, motor, duration_ms))
            self._queue.sort(key=lambda item: item[0])

    def tick(self):
        """Call once per bridge-loop iteration (~60Hz)."""
        now = time.monotonic()
        due = []
        with self._lock:
            while self._queue and self._queue[0][0] <= now:
                due.append(self._queue.pop(0))
        for _, motor, duration_ms in due:
            try:
                # Positional, matching triggerVibration()'s plain-parameter
                # signature in sketch.ino -- see set_ai_status note above.
                Bridge.call("trigger_vibration", motor, duration_ms)
            except Exception:
                pass


class BridgeMotionSensorAdapter:
    """Drop-in for game.motion_sensor.MotionSensor, sourced from the
    Bridge instead of a direct I2C read."""

    def __init__(self, controller):
        self._controller = controller

    def start(self):
        return self

    def get_intensity(self):
        return self._controller.get_motion_intensity()

    def get_tilt(self):
        return self._controller.get_tilt()

    def get_shake_intensity(self):
        return self._controller.get_shake_intensity()

    def stop(self):
        pass


class BridgeMicSensorAdapter:
    """Same idea as BridgeMotionSensorAdapter, for the MAX9814 mic on A3."""

    def __init__(self, controller):
        self._controller = controller

    def start(self):
        return self

    def get_intensity(self):
        return self._controller.get_mic_intensity()

    def stop(self):
        pass


def _bridge_loop(controller, game, haptics):
    """user_loop passed to App.run(): polls controller state, mirrors
    the fatigue level onto the game object, pushes AI status, and
    drains queued haptics, once per tick."""
    controller.poll()
    game.fatigue_level = controller.get_fatigue_level()
    controller.push_ai_status()
    haptics.tick()
    time.sleep(1.0 / 60.0)


def main():
    pygame.init()

    from game import Game

    game = Game(fullscreen=True)

    controller = ControllerBridge(game=game)
    controller.start()

    game.motion_sensor = BridgeMotionSensorAdapter(controller).start()
    game.mic_sensor = BridgeMicSensorAdapter(controller).start()

    haptics = HapticsBridge()
    game.haptics = haptics

    # App.run() starts the UNO Q Bridge runtime; run on a background
    # thread so pygame keeps the main thread for its display/event loop.
    bridge_thread = threading.Thread(
        target=App.run,
        kwargs={"user_loop": lambda: _bridge_loop(controller, game, haptics)},
        daemon=True,
    )
    bridge_thread.start()

    try:
        game.run()
    except Exception:
        pygame.quit()
        raise


if __name__ == "__main__":
    main()