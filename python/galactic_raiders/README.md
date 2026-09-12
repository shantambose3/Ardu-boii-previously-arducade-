# SPACE-RACER: THE JOURNEY BEYOND

An 8-bit horizontal arcade racer-shooter built with `pygame-ce`, inspired
from my favourite character from 'invincible' comics: Space Racer and reworked into a full
shooter with 4 weapons, 3 themed layers of 10 waves + bosses each,
and lightweight adaptive enemy AI suitable for UNO Q.

## Running it

```
pip install pygame-ce
python3 main.py
```

## Controls

| Key            | Action                                   |
|----------------|-------------------------------------------|
| Arrows/WASD/JOYSTICK| Move (bike + alien racer)                 |
| Z / J          | **A** — Vacuum Nails (continuous stream)   |
| X / K          | **B** — Mjolnir (boomerang gun throw)      |
| C / L          | **X** — Infinity Ray (3 uses per layer run, horizontal beam)|
| V / I          | **Y** — Bombs (lob forward, explode on contact or fuse)   |
| Up / Down      | Menu navigation                            |
| Enter          | Confirm / start / restart                  |
| Esc            | Quit / back                                |

## The player

An 8-bit space-bike ridden by a green alien racer. 5 lives per run.

## The 4 weapons

- **A — Vacuum Nails**: the bread-and-butter weapon. Holds down for a
  continuous stream of fast, weak nail bullets.
- **B — Mjolnir**: throws the rider's gun forward like a boomerang; it
  flies out, then returns, damaging enemies on both legs of the trip.
- **X — Infinity Ray**: a screen-obliterating horizontal beam that
  sweeps across the full width of the field at your current height.
  Limited to 3 uses per layer run — regular enemies caught in it are
  wiped out instantly; bosses take heavy damage but some can dodge it
  (see below).
- **Y — Bombs**: lobs a bomb forward in an arc. It detonates the
  instant it touches an enemy, or after a short fuse if it doesn't hit
  anything first, dealing radius damage to every enemy caught in the
  blast. Never hurts you.

## The 3 layers (10 waves + boss each)

### Layer I — Viltrum Invasion
Armored soldiers. Big, tough hitboxes that are easy to *hit* but hard
to *damage*. Basic grunts still only attack in melee (ramming you),
but brutes and the boss carry laser cannons instead. Their boss,
**General N**, is a fast attack ship that's evasive, consistently
jukes the Infinity Ray, and fires twin laser bolts rather than
ramming you.

### Layer II — Terrible Twins
Highly advanced but fragile fast gunners. The boss fight pits you
against **Gunner Eye** and **Melee Eye** — a Terraria-twins-inspired
regenerating pair. Gunner Eye hangs back and lays down continuous
rapid gunfire but never melees; Melee Eye has no ranged attack at all
and instead relentlessly charges and rams you. Take one down and it
goes into a "downed" limbo: if you don't finish its partner within the
regen window, the downed twin heals back up. Kill both within the
window and neither regenerates. The Infinity Ray damages the twins
easily — no evasion tricks here.

### Layer III — Beast Among Beasts
A chaotic mix of weak and strong space beasts. They're tanky and hard
to hit/damage, and uncoordinated enough to occasionally clip and hurt
each other. The boss, **Skull O' Cthulhu**, is a durable cosmic-horror
head that breathes a rapid 3-shot volley of fire and deals 2 lives per
melee hit when it charges, and can dodge the Infinity Ray if you fire
it carelessly from long range (it "sees it coming").

Layer III intentionally does **not** use the adaptive spawn AI — its
identity is chaos, not learned tactics.

## Adaptive enemy AI

Waves on Layers I & II use a lightweight local statistical model
(`game/adaptive_ai.py`) that tracks where you like to sit and which
weapons you favor, then biases spawn formations and dive rates toward
countering your habits over the course of a layer run. Bosses on every
layer use their own smaller tracker that leans into whichever weapon
has hurt them most and gets progressively harder the longer the fight
goes on.

## After a layer boss

Clear a layer's boss and you're offered a choice: continue the same
layer (starts over at wave 1, with the difficulty pressure already
built up), pick a different layer, or quit.

## Project layout

```
game/
  constants.py    window/tuning/enum/stat tables
  pixel_art.py    8-bit sprite grids (player, enemies, bosses, glyphs)
  adaptive_ai.py  lightweight player/boss "learning" trackers
  player.py       player movement, 4-weapon kit, life/hit handling
  enemy.py        wave enemy state machine + per-layer behavior
  boss.py         the 3 unique boss fights and their mechanics
  bullets.py      nails, mjolnir, bombs, infinity beam (horizontal)
  formation.py    wave building, sway/dive logic, adaptive spawn bias
  background.py   scrolling starfield (horizontal)
  particles.py    explosions, score popups
  sound.py        procedurally generated 8-bit sound effects
  helpers.py      small math/drawing utilities
  game.py         the state machine: title/select/play/boss/etc.
main.py           entry point
```
