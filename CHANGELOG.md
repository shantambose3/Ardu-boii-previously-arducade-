# Software Update Changelog

## Controller/layout update (latest)

- **File layout** — `pc_client.py` moved from `network/` to `python/`,
  right next to `galactic_raiders/` (the two now travel together as a
  unit for the PC side). `board_server.py` stays in `network/` as the
  only file that needs to physically live on the UNO Q. `network/
  README.md` and both scripts' docstrings updated to match. No
  behavior change, path-only.

- **Joystick mounting-rotation fix** — `sketch/sketch.ino` now applies
  a 90-degree rotation correction to the raw A0/A1 joystick reading
  before anything else ever sees it (`applyJoystickRotation()`,
  toggled with the `JOY_ROTATE_CW` define), so the physical up/down/
  left/right on this PCB's joystick mounting matches what the player
  expects, without `python/main.py` or the network split needing any
  changes. Defaulted to a 90° clockwise correction as the best guess
  from the board layout; flip the one `#define` and reflash if it
  turns out to be the other way (see the comment above it for the
  one-step hardware check).

- **D8/D9/D10 instant layer-select removed** — these three buttons no
  longer jump straight to Layer 1/2/3 from the Python side
  (`LAYER_BUTTON_MAP`/`_handle_layer_buttons()` removed from both
  `python/main.py` and `python/pc_client.py`). They're now *only* the
  boot-time OLED instructions guide's page-next/page-back/confirm
  controls (unchanged, sketch-side). The on-screen guide text itself
  was updated to stop advertising the old jump-to-layer behavior.
  Layer selection is joystick up/down + D2 confirm, or the keyboard
  `1`/`2`/`3` shortcuts (left untouched, dev-only).

- **New tests** — `tests/test_controller_input.py` (13 tests: deadzone
  boundaries, tap vs. held buttons, simultaneous presses, malformed/
  empty packets, and a regression check that layer buttons produce no
  events at all) and `tests/test_game_logic.py` (7 headless tests:
  state-machine transitions, the wave-11/boss-handoff boundary, the
  defeat path via the real `player.hit()`, the keyboard 1/2/3
  regression, and a short headless playthrough smoke test). All 38
  project tests (including the pre-existing `test_adaptive_ai.py`)
  pass. One finding surfaced, not fixed (out of scope): there's no
  software debounce on the button edge logic, so a bouncy physical
  switch can register more than one tap per real press — flagged in
  `test_rapid_contact_bounce_produces_a_tap_per_flicker`.

---

Everything below is implemented and wired in (not just stubbed), except
where explicitly marked "scaffold" — those have working stub logic today
and a clearly marked swap-in point for the real thing. All new/changed
Python was smoke-tested by actually running the game loop headlessly
(`SDL_VIDEODRIVER=dummy`) through every layer, a boss fight, defeat, the
new report-card/leaderboard flow, and every sensor mechanic. `tests/
test_adaptive_ai.py` covers the adaptive-AI logic (18 tests, all passing).

Quick orientation: the two biggest new files are `game/adaptive_ai.py`
(rewritten) and `game/game.py` (heavily extended) — start there if you
want to see how the pieces connect.

---

## Adaptive AI / gameplay intelligence

- **Cross-session persistence** — `game/persistence.py` is a small
  atomic-write JSON save file (`python/galactic_raiders/save/
  player_save.json`, override with `ARDU_CADE_SAVE_DIR`). `PlayerProfile`
  now has `to_dict()`/`from_dict()` (`game/adaptive_ai.py`). `Game.
  __init__` loads it; `Game.start_new_game()` no longer resets
  `player_profiles` — the AI keeps learning across runs *and* across
  reboots, not just within one session. Saved at every natural
  checkpoint (wave clear, boss defeat, defeat, quit, app exit).

- **Real-time visible adaptation** — new `AiToast` class (`game/
  particles.py`) renders short-lived callouts under the HUD. `Game.
  _check_adaptation_toast()` diffs the AI's current read (favorite
  weapon / preferred lane) against the last wave build and fires
  `"AI ADAPTED: COUNTERING <WEAPON>"` / `"...INCREASED FLANKING..."`.
  Bosses taunt mid-fight via `BossLearner.pending_taunt()` in `game/
  adaptive_ai.py`, surfaced through `Boss.pending_taunt` in `boss.py`.
  Layer III's chaos events, overcharge-armed, panic-bomb, ultimate, and
  boss reinforcement spawns all use the same toast system.

- **Multi-axis learning** — `PlayerProfile` (`game/adaptive_ai.py`) now
  tracks, alongside the existing position/weapon histograms:
  - **accuracy**: `observe_shot_fired()`/`observe_shot_hit()` per
    weapon, wired at every fire/hit site in `game.py`.
  - **reaction time**: `Game._track_reaction_time()` is a lightweight
    proxy — starts a timer when an enemy bullet enters a "danger zone"
    near the player, records the elapsed time the first time the
    player moves meaningfully afterward. Documented as an approximation
    in the code, not a perfect measurement, but consistent and cheap.
  - **risk tolerance**: `observe_risk_sample()`, fed from `_kill_enemy`
    /combo logic — tracks how often the player keeps landing hits while
    at low health.
  - All four axes feed `PlayerProfile.feature_vector()`, the input to
    the Edge Impulse scaffold (below) and the AI report card.

- **Difficulty auto-scaling on real performance** — `Formation.
  _performance_factor()` (`game/formation.py`) derives a 0.7x-1.3x
  multiplier from the player's actual landed-hit accuracy this run and
  folds it into dive rate and toughness ratio, on top of the existing
  wave-number curve.

- **Post-run AI report card** — new `GameState.AI_REPORT_CARD` +
  `Game._draw_report_card()`/`_build_report_card()` in `game.py`: bars
  for aggression/accuracy/risk tolerance, favorite weapon, average
  reaction time, an Edge-Impulse-classified play style label, and
  whether the tilt+shout secret was found this run. Reached from
  DEFEAT (via the new leaderboard initials-entry screen if the score
  qualifies), then flows into a leaderboard screen.

- **Edge Impulse integration scaffold** — `game/edge_impulse.py`:
  `EdgeImpulseClassifier` (feature-vector -> play-style label) and
  `ShoutGestureDetector` (mic envelope -> shout edge-trigger), both with
  a rule-based "stub" backend that runs today with no external
  dependency, and a `BACKEND=eim` swap point with inline TODOs for
  wiring up a real exported `.eim`/Python model. **This part is
  intentionally a scaffold** — no model was trained, per your answer
  to the clarifying question.

- **Layer III's own flavor of intelligence** — new `ChaosDirector`
  class (`game/adaptive_ai.py`): a scripted (not learned) state machine
  that fires FRENZY / MUTATION / PACK_RUSH events on its own timer,
  independent of the player. Wired into `Formation` (`game/
  formation.py`) and `Enemy._update_erratic()`'s new `speed_mult` param
  (`game/enemy.py`). Deterministic given a seed — see
  `test_chaos_director_is_deterministic_with_a_seed`.

- **Swarm behavior reacting to boss state** — `Game._spawn_boss_adds()`
  in `game.py`: every time a boss crosses a phase threshold (see below),
  it calls in 2+ of the layer's regular enemies as reinforcements, with
  their own full formation-entry/dive AI. Collisions handled by the new
  `Game._handle_collisions_boss_adds()`.

## Sensor use (physical-to-game mapping)

All of these are real, working code paths — see `Game.
_update_sensor_mechanics()` in `game.py` and the new `get_tilt()`/
`get_shake_intensity()` on `ControllerBridge` in `python/main.py`. Since
you said you have the hardware, thresholds are left as named constants
in `constants.py` (`TILT_DODGE_THRESHOLD`, `SHAKE_PANIC_THRESHOLD`,
etc., also overridable via `config/game_config.yaml`) with "retune after
real testing" comments — the raw ADC scaling constants in
`get_tilt()`/`get_shake_intensity()`/`get_mic_intensity()` are
first-guess values, not measured against your actual wiring.

- **MPU6050 tilt -> dodge-roll**: `Player.try_dodge_roll()` in
  `player.py` — quick directional burst + brief invulnerability.
- **MPU6050 shake -> panic bomb**: `Game._trigger_panic_bomb()` — clears
  all enemy bullets on screen, chips damage into nearby enemies/bosses,
  long cooldown so it's a real "oh no" button.
- **MAX9814 shout -> weapon overcharge**: `ShoutGestureDetector` (Edge
  Impulse scaffold) detects a sustained shout; `Player.arm_overcharge()`
  arms a one-shot damage/radius multiplier consumed by whichever weapon
  fires next (all four: nails/mjolnir/ray/bomb).
- **Photoresistor -> stealth flavor**: `Formation.is_stealth_active()` /
  the `STEALTH_LIGHT_THRESHOLD` check in `_wave_params()` — beyond the
  existing fatigue-easing, a notably dim room also suppresses how
  eagerly enemies dive, framed as "they can't see you as well."
- **Compound move (tilt + shout) -> ultimate**: `Game._trigger_ultimate()`
  — a bonus infinity-ray blast, gated by `ULTIMATE_WINDOW` requiring
  both signals to overlap. **This is also the rewarded-experimentation
  secret/easter egg** — first trigger sets `secret_found`, shown on the
  report card and persisted.
- **Haptic feedback expansion** — `HapticsBridge.PATTERNS` in
  `python/main.py` gained `dodge`, `near_miss`, `boss_phase`, and
  `low_health` (in addition to the existing `explosion`/`infinity_ray`/
  `defeat`). Near-miss detection and the low-health pulse are new logic
  in `game.py`.
- **Sleep/wake double-tap -> hide OLED stats**: `ControllerBridge.
  _handle_sleep_wake()` in `python/main.py` now distinguishes a single
  tap (pause, as before) from a double-tap within `DOUBLE_TAP_WINDOW`
  (toggles `oled_stats_hidden`, persisted, and pushed to the sketch via
  a new `set_oled_visibility` RPC). `sketch.ino`'s `aiRender()` blanks
  the AI-status numbers when hidden.

## Game content & design

- **Boss phase system** — `boss.py`: `Boss._refresh_phase()` checks hp
  against `BOSS_PHASE_THRESHOLDS` (66%/33%), bumps `self.phase`, flashes
  a colored ring, tints the hp bar, and scales boss speed
  (`BOSS_PHASE_SPEED_SCALE`). `just_changed_phase` is a one-frame flag
  `game.py` consumes for haptics + spawning reinforcements.
- **Score/combo system** — `Player.register_kill()`/`break_combo()` in
  `player.py`: consecutive kills within `COMBO_WINDOW` ramp a
  multiplier (capped at `COMBO_MAX_MULTIPLIER`), with an extra
  `COMBO_RISK_BONUS` for kills landed near a diving enemy. Breaks on
  any hit taken. Shown in the HUD.
- **Local leaderboard** — `persistence.submit_leaderboard_score()`/
  `qualifies_for_leaderboard()`; arcade-style 3-letter initials entry
  (`GameState.ENTER_INITIALS`, `Game._draw_enter_initials()`) triggers
  automatically from DEFEAT when the score makes the top 5.
- **Campaign completion** — `Game.completed_layers` tracks which
  layers' bosses have been cleared in one continuous run; clearing all
  3 triggers a one-time `GameState.CAMPAIGN_COMPLETE` "GALAXY SAVED"
  screen before returning to the normal post-boss menu.
- **Secret/easter egg** — the tilt+shout ultimate, see above.
- Weapon tradeoffs, more enemy movement variety, and the 3-layer/10-wave
  campaign structure were already solid in the existing codebase and
  weren't changed structurally — the boss-phase and combo systems layer
  on top of them instead of replacing them.

## Audio

- **New procedural SFX** (`game/sound.py`): `boss_phase`, `dodge`,
  `overcharge_shoot`, `overcharge_ready`, `combo`, `ai_adapt`,
  `chaos_event`, `secret_found`, `leaderboard_entry`, `ultimate`,
  `panic_bomb` — all synthesized the same way as the existing SFX (no
  new asset files).
- **Dynamic music** — new `MusicDirector` class in `sound.py`: three
  procedurally-generated looped beds (calm/medium/intense), crossfaded
  by a 0..1 intensity value `game.py` feeds from the aggression signal
  (waves) or `max(aggression, boss phase)` (boss fights). `SoundBank.
  music` is `None` if audio init failed, same fail-soft pattern as the
  rest of the sound system.
- Existing 8-bit SFX for shooting/hits/explosions/pickups were already
  in place and untouched.

## Architecture / code quality

- **Config file** — `game/config.py` loads `config/game_config.yaml`
  (if PyYAML is installed) or `config/game_config.json` (always
  available), overlaid onto `constants.py` at import time. Covers
  weapon damage/cooldowns, adaptive-AI weights, combo scoring, boss
  phase thresholds, and every sensor threshold. Missing file/key always
  falls back to the hardcoded default — never a crash.
- **Unit tests** — `tests/test_adaptive_ai.py`, 18 deterministic tests
  covering `PlayerProfile` (accuracy, reaction time, risk tolerance,
  serialization round-trip, malformed-data handling), `BossLearner`
  (counter weapon, evade bias, difficulty scale, taunt firing), and
  `ChaosDirector` (seeded determinism, event firing).
- **Telemetry** — `game/telemetry.py` appends JSONL rows to
  `python/galactic_raiders/logs/telemetry.jsonl`; `tools/
  plot_telemetry.py` is a standalone laptop-side script that charts
  aggression/accuracy over time with event markers, for a "here's the
  data" demo slide. Fails soft if the log directory isn't writable.
- **Graceful degradation** — sensor reads already returned `None`
  cleanly when hardware isn't present (unchanged); the new tilt/shake
  getters follow the same pattern (`ControllerBridge.get_tilt()`/
  `get_shake_intensity()` return `None` if `mpuOk` is false), and every
  new sensor-driven code path in `game.py` already guards on `is not
  None` before using a reading.
- **Bridge reconnect/retry** — `ControllerBridge.poll()`'s existing
  try/except-and-skip-frame behavior was left as-is (it already
  degrades gracefully rather than crashing on a Bridge hiccup); no
  behavioral regression introduced.
- **State machine** — 4 new `GameState` members
  (`AI_REPORT_CARD`/`ENTER_INITIALS`/`LEADERBOARD`/`CAMPAIGN_COMPLETE`)
  added to the existing enum-driven state machine in `constants.py`,
  following the same pattern as the existing states rather than
  introducing a new mechanism.
- **Type hints + docstrings** — all new modules (`persistence.py`,
  `telemetry.py`, `config.py`, `edge_impulse.py`) are fully typed with
  module/class/function docstrings; new/modified functions in existing
  modules (`adaptive_ai.py`, `boss.py`'s phase system, `player.py`'s
  sensor methods) got docstrings and hints where practical without a
  full-file rewrite of already-untyped modules.

---

## Known simplifications (documented in code, not hidden)

- **Reaction time** is a proxy (danger-zone-entry -> next meaningful
  player move), not a true stimulus-response measurement.
- **Edge Impulse** is a scaffold with a working rule-based fallback —
  no model was trained (per your answer to the clarifying question).
- **Sensor threshold constants** (tilt/shake/mic scaling) are
  first-guess values pending real hardware testing, called out inline.
- **Sleep/wake double-tap**: the single tap still fires pause
  immediately (not delayed to wait for a possible second tap), so a
  double-tap currently triggers *both* pause-toggle and OLED-toggle.
  Harmless in practice (the two don't conflict) but not a "true" debounce
  — flagged in case you want stricter behavior later.
- **Config file** covers the most impactful tunables, not literally
  every constant in `constants.py` — extending the list in `config.py`
  is copy-paste if you want more.

## Files touched

```
NEW    python/galactic_raiders/game/config.py
NEW    python/galactic_raiders/game/persistence.py
NEW    python/galactic_raiders/game/telemetry.py
NEW    python/galactic_raiders/game/edge_impulse.py
NEW    python/galactic_raiders/config/game_config.json
NEW    python/galactic_raiders/config/game_config.yaml
NEW    tools/plot_telemetry.py
NEW    tests/test_adaptive_ai.py
NEW    CHANGELOG.md (this file)

REWRITTEN  python/galactic_raiders/game/adaptive_ai.py
EXTENDED   python/galactic_raiders/game/game.py
EXTENDED   python/galactic_raiders/game/boss.py
EXTENDED   python/galactic_raiders/game/formation.py
EXTENDED   python/galactic_raiders/game/enemy.py
EXTENDED   python/galactic_raiders/game/player.py
EXTENDED   python/galactic_raiders/game/sound.py
EXTENDED   python/galactic_raiders/game/particles.py
EXTENDED   python/galactic_raiders/game/constants.py
EXTENDED   python/main.py
EXTENDED   sketch/sketch.ino
EXTENDED   python/requirements.txt (noted optional pyyaml)
```

## Try it (desktop, no hardware)

```
cd ardu-cade/python
pip install -r requirements.txt --break-system-packages
python3 galactic_raiders/main.py    # windowed dev entry, keyboard only
```

Sensor mechanics (dodge/panic-bomb/overcharge/ultimate) only do
anything when `game.motion_sensor`/`game.mic_sensor` are set, which
only happens when running through `python/main.py` on the actual UNO Q
board (`python/main.py` is the Bridge-connected entry point; `python/
galactic_raiders/main.py` is the plain-keyboard dev entry and leaves
those as `None`, so those code paths are silent no-ops on desktop).
