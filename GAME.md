# Galactic Raiders

A side-scrolling shoot-'em-up controlled by real hardware: buttons and a
joystick for movement/weapons, and three onboard sensors (accelerometer,
photoresistor, mic) that layer extra mechanics on top. It runs either
directly on the UNO Q (`python/main.py`) or split across the board and a
PC (`network/board_server.py` + `python/pc_client.py`) -- controls and
mechanics are identical either way.

## Controls

| Input | Action |
|---|---|
| Joystick | Move (2D, boxed to your side of the field) |
| D2 (A) | **Vacuum Nails** -- fire |
| D3 (B) | **Mjolnir** -- throw |
| D4 (X, held) | **Infinity Ray** -- fire while held |
| D5 (Y) | **Bomb** -- lob |
| D12 (sleep/wake) | Tap: pause. Double-tap: hide/show OLED stats |
| D8/D9/D10 | Page/confirm the OLED instructions guide (menus otherwise use joystick + confirm) |

## Weapons

You've got four weapons, each with its own rhythm -- there's no reload,
just cooldowns and (for one of them) limited charges.

- **Vacuum Nails (A)** -- a fast, cheap stream of small bullets. Low
  damage per hit, but the cooldown is short enough to fire almost
  continuously. Your default, reliable weapon.
- **Mjolnir (B)** -- a boomerang you throw straight out; it travels a
  limited range before returning to you, hitting anything in its path
  both ways. Slower cooldown than nails, but hits harder and can tag
  multiple enemies in one throw.
- **Infinity Ray (X, held)** -- a short but devastating beam that
  obliterates almost anything it touches. You only get a handful of
  charges per layer, so it's best saved for bosses or getting swarmed.
  Charges refill when you start/re-enter a layer.
- **Bomb (Y)** -- lobbed in an arc, explodes on contact or after a short
  fuse, damaging everything in a blast radius. Good for hitting several
  enemies at once or softening up something tanky.

**Combo scoring:** kills chained close together build a score multiplier
that keeps climbing the faster you chain kills, up to a cap. Let it go
quiet for a couple seconds and the combo resets. Landing a kill on a
diving/charging enemy while it's still close to you (risky play) gives
an extra bonus on top of the combo multiplier.

## Sensors & sensor-mapped mechanics

Three sensors read real-world input and feed it into mechanics you won't
find on the button/joystick alone:

- **GY-521 (accelerometer)** -- reads the board's tilt and how hard/fast
  you shake it.
  - **Tilt -> Dodge-Roll:** tilt the board sharply and you burst in that
    direction with a moment of invulnerability. Short cooldown, meant to
    be used often to dodge incoming fire.
  - **Shake -> Panic Bomb:** shake the board hard enough and it clears
    every enemy bullet near you and chips damage into anything close by
    (including bosses). Long cooldown -- it's an "oh no" button, not
    something to spam.

- **MAX9814 mic** -- reads ambient loudness.
  - **Sustained shout -> Overcharge:** yell loud enough for long enough
    and your next weapon shot comes out boosted (extra damage/blast
    radius). One-shot -- it's consumed by whatever weapon you fire next.

- **Photoresistor (light sensor)** -- reads how bright the room is.
  - **Dim room -> eased difficulty:** a darker room nudges wave
    difficulty down slightly, on the read that a dim room might mean a
    tired/late-night player. It only ever eases waves, never boss
    fights, and only up to a small cap -- it won't trivialize the game.

**The secret -- Tilt + Shout Ultimate:** combine a big tilt with a loud
shout within the same short window and you'll trigger a rare, powerful
bonus Infinity Ray blast that doesn't cost you a real charge. It's not
explained anywhere in-game -- it's meant to be found by experimenting
with the sensors together, not by button-mashing. Long cooldown, and the
game remembers the first time you find it.

## Layers (worlds)

Three layers, each with its own enemy roster and boss:

- **Layer I -- Viltrum Invasion:** armored soldiers. Grunts ram you in
  melee; brutes and the boss, General N, carry laser guns instead.
  Tough to damage, but big and easy to hit.
- **Layer II -- Terrible Twins:** advanced, fast gunners. Fragile
  individually but relentless in numbers. Boss fight is two enemies at
  once -- one ranged (Gunner Eye), one melee (Melee Eye) -- both with
  regenerating health.
- **Layer III -- Beast Among Beasts:** feral space beasts. Chaotic,
  tanky, and uncoordinated -- they'll even friendly-fire each other.
  Boss: Skull O'Cthulhu.

Clear all three layers' bosses in one continuous run for the Campaign
Complete ending.

## Adaptive AI

The game quietly tracks how you play each layer -- your aggression,
accuracy, reaction time, favorite weapon, and how much risk you take --
and adjusts enemy behavior to match over the course of a run. After a
run, an AI Report Card summarizes what it picked up on. This is
separate from the sensor mechanics above; it runs off your in-game
actions, not sensor input.
