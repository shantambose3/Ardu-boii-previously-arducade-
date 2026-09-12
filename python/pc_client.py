"""
Cyber Deck -- PC side, "run the actual game here" mode.

Pairs with network/board_server.py, which stays on the UNO Q. This
script lives next to galactic_raiders/ instead (it needs that folder
right beside it, so the two travel together) -- the UNO Q keeps doing
exactly what it's good at -- reading D2-D5/D8-D10 buttons, the
joystick, and the A2/A3/GY-521 sensors off real hardware via
sketch/sketch.ino -- and streams that over the network instead of
running the game itself. This script receives that stream, turns it
into the same synthetic pygame key events python/main.py's
ControllerBridge used to generate locally, and runs galactic_raiders/
game/ unchanged, using your PC's CPU/GPU instead of the UNO Q's.

Sensor -> difficulty behavior is unchanged from the original single-
board setup: the A2 photoresistor's fatigue_level still only eases
WAVE difficulty (see get_fatigue_level() below, ported straight from
python/main.py), motion/mic intensity still feed the same
motion_sensor/mic_sensor hooks in game.py, and this script pushes the
adaptive-AI status (learning %, favorite weapon, aggression,
fatigue-ease %) back to the board every tick so the OLED keeps
updating -- same data python/main.py's push_ai_status() computed, just
sent over UDP instead of the local Bridge.

Run this on your PC (from inside ardu-cade/python/):

    python3 pc_client.py --board-ip 192.168.1.22

`--board-ip` is your UNO Q's IP (the one you SSH into). Requires
`pygame-ce` and `numpy` (see requirements.txt in this same folder) --
nothing else; this script does NOT need arduino.app_utils, msgpack,
etc. since it never talks to the Bridge directly.

Setup: copy (or keep) this whole `ardu-cade` folder together on your
PC -- this script expects `./galactic_raiders` right next to it, same
folder. board_server.py (in ../network/) is the only piece that needs
to physically live on the UNO Q.
"""

import argparse
import json
import os
import socket
import sys
import threading
import time

GAME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "galactic_raiders")
sys.path.insert(0, GAME_DIR)

import pygame  # noqa: E402

CONTROL_PORT = 5551   # board -> PC: controller + sensor state
STATUS_PORT = 5552    # PC -> board: AI status (OLED) + haptic buzzes

# Same mappings as python/main.py's ControllerBridge -- keep these two
# files in sync if you rewire physical buttons.
BUTTON_KEY_MAP = {
    0: pygame.K_v,       # D2 -> bomb
    1: pygame.K_c,       # D3 -> infinity ray
    2: pygame.K_z,       # D4 -> vacuum nails (held)
    3: pygame.K_x,       # D5 -> mjolnir
}
BUTTON_HELD_KEYS = {pygame.K_z}

MENU_KEY_MAP = {
    0: pygame.K_RETURN,
    1: pygame.K_ESCAPE,
}

JOY_DEADZONE = 80

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


class NetworkController:
    """Network-sourced equivalent of python/main.py's ControllerBridge.
    A background thread receives UDP packets from board_server.py and
    updates state here; poll() (called once per game tick, same as the
    original) turns state changes into synthetic pygame key events."""

    def __init__(self, game=None):
        self._lock = threading.Lock()
        self._latest = None
        self._last_buttons = 0
        self._last_sleep_wake = False
        self._last_joy_left = False
        self._last_joy_right = False
        self._last_joy_up = False
        self._last_joy_down = False
        self.latest_accel = (0, 0, 0)
        self.latest_light_level = 0
        self.latest_mic_level = 0
        self.mpu_ok = False
        self.game = game
        self._sock = None
        self._running = False
        self._last_accel_mag = None

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", CONTROL_PORT))
        self._running = True
        threading.Thread(target=self._recv_loop, daemon=True).start()
        return self

    def _recv_loop(self):
        while self._running:
            try:
                raw, _addr = self._sock.recvfrom(4096)
                data = json.loads(raw.decode("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("type") != "controller_state":
                continue
            with self._lock:
                self._latest = data

    def poll(self):
        """Call once per game tick (mirrors ControllerBridge.poll())."""
        with self._lock:
            data = self._latest
            self._latest = None
        if data is None:
            return
        self._handle_buttons(data.get("buttons", 0))
        # NOTE: layerButtons (D8/D9/D10) is deliberately NOT handled here
        # anymore -- those three buttons only page/confirm the sketch's
        # boot-time OLED instructions guide now (see sketch.ino's
        # handleInstructionButtons()); they no longer instant-jump to a
        # layer during LAYER_SELECT. The board still sends the field;
        # we just ignore it. Layer choice is joystick up/down + confirm
        # (or the 1/2/3 keyboard shortcuts in game.py, for desktop dev).
        self._handle_sleep_wake(bool(data.get("sleepWake", False)))
        self._handle_joystick(data.get("joyX", 0), data.get("joyY", 0))
        self.latest_light_level = data.get("lightLevel", 0)
        self.latest_mic_level = data.get("micLevel", 0)
        self.latest_accel = (
            data.get("accelX", 0), data.get("accelY", 0), data.get("accelZ", 0),
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
                self._post(key, now)
            elif now:
                self._post(key, True)
                self._post(key, False)

            if now and bit in MENU_KEY_MAP and self._in_menu_state():
                menu_key = MENU_KEY_MAP[bit]
                self._post(menu_key, True)
                self._post(menu_key, False)
        self._last_buttons = buttons

    def _in_menu_state(self):
        if self.game is None:
            return False
        from game.constants import GameState
        return self.game.state not in (GameState.PLAYING, GameState.BOSS_FIGHT)

    def _handle_sleep_wake(self, sleep_wake):
        now = sleep_wake
        was = self._last_sleep_wake
        self._last_sleep_wake = now
        if now and not was:
            self._post(pygame.K_p, True)
            self._post(pygame.K_p, False)

    def _handle_joystick(self, joy_x, joy_y):
        # Physical joystick reports inverted on this wiring -- flip both
        # axes here (matches the "flip sign if inverted" note in
        # main.py's ControllerBridge). Board keeps sending raw values;
        # this is a display/mapping fix only.
        joy_x = -joy_x
        joy_y = -joy_y
        want_left = joy_x < -JOY_DEADZONE
        want_right = joy_x > JOY_DEADZONE
        want_up = joy_y < -JOY_DEADZONE
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
        if not self.mpu_ok:
            return None
        ax, ay, az = self.latest_accel
        magnitude = (ax * ax + ay * ay + az * az) ** 0.5
        return min(1.0, magnitude / 20000.0)

    def get_tilt(self):
        """(tiltX, tiltY), each roughly -1..1, or None if the GY-521
        isn't reporting. Mirrors ControllerBridge.get_tilt() in
        python/main.py."""
        if not self.mpu_ok:
            return None
        ax, ay, _ = self.latest_accel
        TILT_SCALE = 9000.0
        return (max(-1.0, min(1.0, ax / TILT_SCALE)), max(-1.0, min(1.0, ay / TILT_SCALE)))

    def get_shake_intensity(self):
        """0..1 "jerk" signal, frame-to-frame change in acceleration
        magnitude. Mirrors ControllerBridge.get_shake_intensity() in
        python/main.py."""
        if not self.mpu_ok:
            return None
        ax, ay, az = self.latest_accel
        mag = (ax * ax + ay * ay + az * az) ** 0.5
        jerk = abs(mag - self._last_accel_mag) if self._last_accel_mag is not None else 0.0
        self._last_accel_mag = mag
        SHAKE_SCALE = 6000.0
        return max(0.0, min(1.0, jerk / SHAKE_SCALE))

    def get_mic_intensity(self):
        MIC_NOISE_FLOOR = 40
        MIC_CEILING = 700
        raw = self.latest_mic_level
        span = max(1, MIC_CEILING - MIC_NOISE_FLOOR)
        return max(0.0, min(1.0, (raw - MIC_NOISE_FLOOR) / span))

    def get_fatigue_level(self):
        """0..1 fatigue signal from the board's A2 photoresistor -- this
        is the actual "sensor input changes difficulty" path: a dimmer
        room -> higher fatigue -> eased WAVE difficulty (never boss
        fights), same formula/caps as python/main.py."""
        PHOTO_DARK = 150
        PHOTO_BRIGHT = 700
        raw = self.latest_light_level
        span = max(1, PHOTO_BRIGHT - PHOTO_DARK)
        fatigue = (PHOTO_BRIGHT - raw) / span
        return max(0.0, min(1.0, fatigue))


class NetworkMotionSensorAdapter:
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


class NetworkMicSensorAdapter:
    def __init__(self, controller):
        self._controller = controller

    def start(self):
        return self

    def get_intensity(self):
        return self._controller.get_mic_intensity()

    def stop(self):
        pass


class NetworkHaptics:
    """Same buzz-pattern/rate-limit logic as python/main.py's
    HapticsBridge, but sends the resulting pulses to the board over UDP
    instead of calling Bridge.call() directly (there is no local
    Bridge on the PC)."""

    PATTERNS = {
        "explosion":    ([("B", 70, 0)], 0.08),
        "infinity_ray": ([("B", 180, 0)], 0.3),
        "defeat":       ([("B", 220, 0), ("B", 220, 260)], 1.0),
    }

    def __init__(self, sock, board_addr):
        self._sock = sock
        self._board_addr = board_addr
        self._lock = threading.Lock()
        self._queue = []
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
        now = time.monotonic()
        due = []
        with self._lock:
            while self._queue and self._queue[0][0] <= now:
                due.append(self._queue.pop(0))
        for _, motor, duration_ms in due:
            self._send({"type": "haptic", "motor": motor, "duration_ms": duration_ms})

    def _send(self, msg):
        try:
            self._sock.sendto(json.dumps(msg).encode("utf-8"), self._board_addr)
        except OSError:
            pass


def push_ai_status(sock, board_addr, controller, game):
    """PC-side equivalent of python/main.py's push_ai_status(): reads
    the live PlayerProfile straight off the local Game object (it's
    running right here now) and sends the same snapshot to the board
    for the OLED, over UDP instead of Bridge.call()."""
    try:
        profile = game.player_profiles.get(game.layer)
        if profile is None:
            return

        LEARNING_SAMPLE_CAP = 150
        learning_pct = int(min(100, profile.samples / LEARNING_SAMPLE_CAP * 100))
        has_data = profile.samples > 0

        fatigue = controller.get_fatigue_level()
        FATIGUE_EASE_CAP_PCT = 35
        fatigue_ease_pct = int(fatigue * FATIGUE_EASE_CAP_PCT)

        msg = {
            "type": "ai_status",
            "learning_pct": learning_pct,
            "samples": min(profile.samples, 65535),
            "favorite_weapon": profile.favorite_weapon() if has_data else "-",
            "aggression_pct": int(profile.avg_aggression() * 100),
            "fatigue_ease_pct": fatigue_ease_pct,
        }
        sock.sendto(json.dumps(msg).encode("utf-8"), board_addr)
    except OSError:
        pass


def _bridge_loop(sock, board_addr, controller, game, haptics):
    """Runs on a background thread at ~60Hz -- same cadence and same
    responsibilities as python/main.py's _bridge_loop, just sourced
    from the network instead of a local Bridge call."""
    while True:
        controller.poll()
        game.fatigue_level = controller.get_fatigue_level()
        push_ai_status(sock, board_addr, controller, game)
        haptics.tick()
        time.sleep(1.0 / 60.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--board-ip", required=True,
        help="IP address of the UNO Q running board_server.py (e.g. 192.168.1.22)",
    )
    args = parser.parse_args()
    board_addr = (args.board_ip, STATUS_PORT)

    pygame.init()

    from game import Game

    game = Game(fullscreen=True)

    controller = NetworkController(game=game).start()
    print(f"[pc_client] listening for controller state on :{CONTROL_PORT}")

    game.motion_sensor = NetworkMotionSensorAdapter(controller).start()
    game.mic_sensor = NetworkMicSensorAdapter(controller).start()

    status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    haptics = NetworkHaptics(status_sock, board_addr)
    game.haptics = haptics

    print(f"[pc_client] sending AI status / haptics to {args.board_ip}:{STATUS_PORT}")

    threading.Thread(
        target=_bridge_loop,
        args=(status_sock, board_addr, controller, game, haptics),
        daemon=True,
    ).start()

    try:
        game.run()
    except Exception:
        pygame.quit()
        raise


if __name__ == "__main__":
    main()