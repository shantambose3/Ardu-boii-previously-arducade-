# ARDU-cade — Space-Racer: The Journey Beyond

A 3D-printed handheld controller built around the Arduino UNO Q, where a joystick,
7 buttons, and three onboard sensors (motion, sound, light) drive a four-weapon
shoot-'em-up whose enemy AI adapts to how *you* play — all running locally, no
cloud, no network dependency required.

> **Note on difficulty:** This is tagged "Advanced" on Hackster because everything
> here — custom PCB, custom enclosure, adaptive AI, full game engine — was built
> from scratch. You don't have to do all of that to get it running. If you're
> comfortable with basic wiring and copy-pasting a few terminal commands, you can
> have the full game playable on a breadboard in **2–3 hours**, sensors and all —
> no PCB fab or 3D printing required to start. Replicating it (fully or partially),
> forking it, or just wiring up one sensor mechanic is very much encouraged —
> open an issue or a discussion with what you tried, I'd love to see it.

Full write-up with photos, video, and design rationale: [Hackster project page](https://www.hackster.io/shantambose3/ardu-cade-a-console-in-a-controller-with-local-adaptive-ai-fd61ae)

---

## Table of Contents
- [What it does](#what-it-does)
- [Prerequisites](#prerequisites)
- [Pin map](#pin-map)
- [Step-by-step build](#step-by-step-build)
- [Running it](#running-it)
- [Software architecture](#software-architecture)
- [Adaptive AI — and why it's simple on purpose](#adaptive-ai--and-why-its-simple-on-purpose)
- [Testing](#testing)
- [Known issues / what's next](#known-issues--whats-next)

---

## What it does

- Joystick + 7 tactile buttons drive movement, four weapons, pause, and menu nav
- MPU6050: sharp **tilt** → dodge-roll, hard **shake** → screen-clearing panic bomb
- MAX9814 mic: **shout** at it to overcharge your next shot
- Photoresistor: dim room slightly eases wave difficulty (never bosses)
- Tilt + shout together → secret, undocumented Infinity Ray blast
- SSD1306 OLED: boot-time control guide, then a live "AI LEARNING" dashboard
- Two vibration motors for haptic feedback
- Runs on a custom 2-layer PCB (EasyEDA Pro) in a 3D-printed shell

## Prerequisites

**Hardware** — see the full BOM on the [Hackster page](https://www.hackster.io/shantambose3/ardu-cade-a-console-in-a-controller-with-local-adaptive-ai-fd61ae); at minimum you'll need an Arduino UNO Q, a joystick, 7 tactile buttons, an MPU6050, a MAX9814, a photoresistor, and an SSD1306 OLED.

**Software**
- [Arduino App Lab](https://docs.arduino.cc/software/app-lab/) — used once, just to flash the MCU sketch
- Python 3 on the UNO Q's Linux side (check with `python3 --version`)
- Python packages — see `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  ```
- [RustDesk](https://rustdesk.com/) — optional, only if you want to view the game running on the board's own screen remotely

Clone the repo:
```bash
git clone https://github.com/shantambose3/Ardu-boii-previously-arducade-.git
cd Ardu-boii-previously-arducade-
```

## Pin map

```
D2  – Bomb (Y) / menu confirm
D3  – Infinity Ray (X) / menu back
D4  – Vacuum Nails (A), held
D5  – Mjolnir (B)
D6  – Left vibration motor
D7  – Right vibration motor
D8  – OLED guide: confirm/start
D9  – OLED guide: page next
D10 – OLED guide: page back
D12 – Sleep/wake: tap = pause, double-tap = hide/show OLED stats
A0  – Joystick X
A1  – Joystick Y
A2  – Photoresistor (light/fatigue sensor)
A3  – MAX9814 mic envelope output
I2C – SSD1306 OLED (0x3C) + MPU6050 (0x68)
```

## Step-by-step build

Each stage below is independently testable — wire one thing, confirm it works, move to the next. If something doesn't respond, you'll know exactly which step to recheck.

1. **Wire up the sensors and controls** per the pin map above (breadboard is fine to start):
   - Joystick → A0 (X), A1 (Y)
   - 7 tactile buttons → D2–D5, D8–D10
   - Photoresistor (with 1kΩ pulldown) → A2
   - MAX9814 mic envelope out → A3
   - MPU6050 + SSD1306 OLED → I2C (MPU6050 @ `0x68`, OLED @ `0x3C`)
   - 2 vibration motors, each through an NPN transistor + flyback diode → D6, D7

2. **Solder the PCB** (or finish breadboard wiring). Double-check the flyback diode orientation on the motor lines before powering on — reversed there is the fastest way to fry a transistor.

3. **Flash the MCU sketch** — open `sketch/sketch.ino` in Arduino App Lab, select the UNO Q, flash. This is the *only* step App Lab is used for (see [Known issues](#known-issues--whats-next) for why).

4. **Set up the Python venv** on the board's Linux side:
   ```bash
   cd python
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Run it** — see [Running it](#running-it) below.

6. **Mount in the case** — print `back-plate.stl` and `front_plate.stl` (linked on the Hackster page), seat the PCB on the back plate's towers, route joystick/buttons through the front plate cutouts.

> **Axis note:** the joystick isn't mounted "upright" relative to how the case is held. Verify direction with one push of the stick after assembly. If inverted, flip the rotation direction in the single rotation function in `sketch.ino` rather than patching it in multiple downstream places.

## Running it

**Standalone** (everything on the UNO Q itself):
```bash
python3 main.py
```

**Split mode** (if the board drops frames — offloads rendering/AI to a PC over UDP):
```bash
# on the PC
python3 pc_client.py

# on the board
python3 network/board_server.py
```
Set `DEFAULT_PC_IP` in `board_server.py` to your PC's actual LAN IP, and give that PC a DHCP reservation or static IP — UDP is fire-and-forget, so a stale IP fails *silently* with no errors on either side.

**Viewing the game on the board's own screen remotely** — use RustDesk (`remote-display/`) rather than xrdp/x11vnc: xrdp fights the existing desktop session, x11vnc is CPU-bound and password-length-limited. RustDesk attaches to the *existing* session and is noticeably snappier for both video and input.

## Software architecture

```
sketch/sketch.ino  (MCU side)
   – reads joystick, 7 buttons, MPU6050, photoresistor, mic
   – drives the OLED (boot guide, then live AI status) and haptics
   – exposes get_controller_state / set_ai_status /
     trigger_vibration / set_oled_visibility over the Bridge
        │
        │  Arduino_RouterBridge (msgpack, request/response)
        ▼
python/main.py  (Linux side)
   – polls controller state once a frame
   – turns buttons/joystick into synthetic pygame key events
   – pushes AI status + haptic requests back over the Bridge
   – runs galactic_raiders/ (the pygame-ce game) unchanged
```

`galactic_raiders/` is self-contained `pygame-ce` — hand-drawn 8-bit sprites, procedurally generated sound, no external art/audio assets.

## Adaptive AI — and why it's simple on purpose

The game tracks aggression, accuracy, reaction time, favorite weapon, and risk tolerance per layer, biasing enemy spawn formations and dive rates against your habits as a run progresses — persisted to disk (`game/persistence.py`) so it keeps learning across sessions, not just within one run.

**This is a rule-based statistical profiler, not a neural net — and that's a design choice, not a shortcut.** Everything runs on-device, in real time, on the UNO Q's own compute: no cloud inference, no API calls, no network dependency. That constraint is exactly why the [Edge Impulse](https://edgeimpulse.com/) hooks in `game/edge_impulse.py` exist as swap-in points instead of being wired up by default — a trained Impulse model still has to run locally, at game framerate, alongside the render loop, on hardware with no GPU to spare for it. "Simple but fully local and instant" was the actual goal, not "as complex as possible." Flip `EI_BACKEND=eim` once a real exported model is wired up and it drops in behind the same interface.

## Testing

38 automated tests (`tests/test_adaptive_ai.py`, `tests/test_controller_input.py`, `tests/test_game_logic.py`) covering deadzone boundaries, tap-vs-held buttons, simultaneous presses, malformed controller packets, state-machine transitions, the boss handoff, the defeat path, and a full headless playthrough (`SDL_VIDEODRIVER=dummy`) through every layer and sensor mechanic.

```bash
pytest tests/
```

## Known issues / what's next

- **App Lab runs games headless** — the App Lab Run button executes inside a Docker container with no access to the host's X11 display, so `pygame` silently falls back to a dummy driver: the game runs (log output appears) but no window shows, even over RustDesk. Fix: run `main.py` from a plain venv directly on the board using the host's real `DISPLAY`; still use App Lab once to flash the sketch.
- **No software debounce** on button edges yet — a bouncy switch can occasionally register more than one tap per press. Flagged, not yet fixed.
- **Next up:** train a real Edge Impulse model on logged telemetry (`game/telemetry.py` → `logs/telemetry.jsonl`) to replace the rule-based classifier stub; fix debounce; possibly a fourth layer.

---

Built for the Arduino UNO Q Challenge — Gaming category. MIT licensed. Feedback, forks, and partial builds welcome — open an issue or a discussion.
