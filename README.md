# 🎮 ARDU-cade

**A handheld arcade controller built on the Arduino UNO Q, playing a custom
8-bit shooter — *Galactic Raiders* — with an adaptive AI that learns you as
you play.**

Built for the **Arduino Physical AI Challenge India 2026** (Robu.in × Arduino).

---

## What is this?

ARDU-cade is a 3D-printed, single-board handheld game controller. The
Arduino UNO Q's MCU side polls all the physical inputs — buttons, joystick,
an MPU6050 accelerometer, a MAX9814 mic, and a photoresistor — while its
onboard Linux MPU runs a Python/pygame-ce game at 60 fps. The two talk to
each other over the UNO Q's built-in Router Bridge, and the connection is
**bidirectional**: the game reads controller state every frame, and pushes
live "AI status" (learning progress, favorite weapon, aggression, fatigue)
back to the sketch, which renders it on the handheld's OLED in real time.

On top of that sits a lightweight, hand-written adaptive AI (no neural
network, no external training) that watches how you play — where you sit,
what you shoot with, how accurate you are, how much risk you take — and
biases enemy spawns, boss behavior, and even a wave-5 "AI verdict"
(extra lives or a confiscated weapon) around your habits.

## Features

- **Full physical controller**: joystick, 4 action buttons, D-pad, a
  sleep/wake button, and 3 sensors, all read from `sketch/sketch.ino` and
  exposed over the Bridge.
- **Live OLED status screen** — driven entirely by data the Python side
  pushes back each frame; the sketch never has to poll for it.
- **Sensor-mapped gameplay mechanics** (not just menu/AI plumbing) — tilt to
  dodge-roll, shake for a panic bomb, shout to overcharge a shot, and a
  hidden tilt+shout ultimate. Room brightness gently eases wave difficulty
  (never boss fights). See [`GAME.md`](GAME.md) for the full breakdown.
- **Adaptive AI** — `PlayerProfile` + `BossLearner` bias spawn lanes, dive
  rates, and boss counter-attacks; a one-shot `MidRunVerdict` after wave 5
  either rewards a struggling run (+2 lives) or punishes a dominating one
  (locks your deadliest weapon for a couple of waves). Deliberately
  disabled on Layer III, whose identity is scripted chaos instead
  (`ChaosDirector`).
- **Two run modes, identical controls/mechanics**:
  - **Single-board** (`python/main.py`) — game renders directly on the
    UNO Q, viewable remotely over a RustDesk stream if there's no monitor
    attached (see [`remote-display/README.md`](remote-display/README.md)).
  - **Networked split** (`network/board_server.py` +
    `python/pc_client.py`) — the board streams controller/sensor data over
    UDP to a PC, which runs the game and AI and streams status/haptics
    back. Use this if the UNO Q struggles to hold 60 fps locally. See
    [`network/README.md`](network/README.md).
- **Persistent player profile** — stats survive across boots (not just
  within a run), saved via `game/persistence.py`.

## Repository layout

```
ardu-cade/
├── sketch/                  Arduino sketch (MCU side): sensors, OLED, Bridge
│   ├── sketch.ino
│   └── sketch.yaml          Board/library manifest (fqbn: arduino:zephyr:unoq)
├── python/                  Game (Linux MPU / PC side)
│   ├── main.py              Single-board entry point
│   ├── pc_client.py         PC-side entry point for split/networked mode
│   ├── requirements.txt
│   └── galactic_raiders/
│       └── game/
│           ├── game.py          Main state machine / game loop
│           ├── adaptive_ai.py   PlayerProfile, BossLearner, MidRunVerdict, ChaosDirector
│           ├── player.py, enemy.py, boss.py, formation.py, bullets.py, ...
│           └── pixel_art.py     Hand-authored sprite grids + palettes
├── network/
│   ├── board_server.py      Runs ON the UNO Q for split mode
│   └── README.md
├── remote-display/
│   ├── setup_rustdesk.sh    Headless display + RustDesk setup for the board
│   └── README.md
├── tests/                   pytest suite (adaptive AI, controller input, game logic)
├── tools/
│   └── plot_telemetry.py
├── GAME.md                  Controls, weapons, layers, sensors, adaptive AI (player-facing)
├── CHANGELOG.md
└── app.yaml                 Arduino App Lab manifest
```

## Hardware

| Component | Notes |
|---|---|
| Arduino UNO Q (ABX00087) | MCU + Linux MPU on one board |
| SSD1306 OLED, 0.96" (I2C) | Live AI status readout |
| PS2-style analog joystick | Movement |
| MPU6050 accelerometer/gyro | Dodge-roll (tilt) + panic bomb (shake) |
| MAX9814 mic (3-pin) | Overcharge (sustained shout) |
| Photoresistor | Eases wave difficulty in dim rooms |
| 3× 12mm + 4× 6mm tactile switches | Action buttons + D-pad |
| 2× coin vibration motors | Haptic feedback |
| 5V 3A supply | Power |

Full BOM, schematic, and photos are in the contest submission PDF.

## Getting started

### 1. Flash the sketch

```bash
arduino-cli compile --fqbn arduino:zephyr:unoq sketch/
arduino-cli upload  --fqbn arduino:zephyr:unoq sketch/
```

Library versions are pinned in [`sketch/sketch.yaml`](sketch/sketch.yaml)
(U8g2, Arduino_RouterBridge, Arduino_RPClite, MsgPack, ArxContainer,
ArxTypeTraits, DebugLog).

### 2a. Run on the board (single-board mode)

```bash
cd python
pip install -r requirements.txt
python main.py
```

If you're running outside the Arduino App Lab container (recommended —
App Lab's Docker sandbox has no access to the host X11 display, so pygame
silently falls back to a dummy driver), use a plain Python venv on the
board instead. See `CHANGELOG.md` for why.

### 2b. Run split across the board + a PC

See [`network/README.md`](network/README.md) — `board_server.py` stays on
the UNO Q, `pc_client.py` runs next to `galactic_raiders/` on your PC.

### 3. (Optional) Headless remote display

If the board has no monitor attached, see
[`remote-display/README.md`](remote-display/README.md) to set up a dummy
X11 display + RustDesk so you can view/play it remotely.

## Testing

```bash
cd ardu-cade
pytest tests/
```

Covers the adaptive AI (`test_adaptive_ai.py`), controller input edge
cases — deadzones, tap vs. held, simultaneous presses, malformed packets
(`test_controller_input.py`) — and headless game-logic smoke tests
(`test_game_logic.py`), including a full playthrough via
`SDL_VIDEODRIVER=dummy`.

## Documentation map

- [`GAME.md`](GAME.md) — controls, weapons, layers, sensor mechanics, and
  the adaptive AI, from the player's side.
- [`CHANGELOG.md`](CHANGELOG.md) — what's changed and why, including
  hardware quirks discovered along the way (joystick mounting rotation,
  App Lab's X11 sandboxing, `pygame.key.get_pressed()` not seeing synthetic
  events).
- [`network/README.md`](network/README.md) — networked split-mode setup.
- [`remote-display/README.md`](remote-display/README.md) — headless
  RustDesk display setup.

## Author

**Shantam Bose** (solo) 
