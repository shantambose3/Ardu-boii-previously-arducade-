# Split mode: UNO Q for input, PC for the game

If the UNO Q struggles to run the game at a good framerate, use this
instead of `python/main.py`. The board keeps reading real hardware
(buttons, joystick, photoresistor, mic, GY-521) and streams that over
WiFi; your PC does all the actual work (pygame rendering, adaptive AI,
physics) using its own CPU/GPU.

No RustDesk needed for this mode -- the game window opens directly on
your PC's own screen.

## What runs where

- **`board_server.py`** (this folder) -- runs ON the UNO Q. Talks to
  `sketch/sketch.ino` over the Bridge exactly like `python/main.py`
  used to, but instead of turning that into local pygame events, sends
  it over UDP to `pc_client.py` on your PC. This is the only file that
  needs to physically live on the board.
- **`../python/pc_client.py`** -- runs on your PC, sitting right next
  to `../python/galactic_raiders/` (the two travel together). Receives
  the UDP stream, turns it into the same synthetic key presses
  `python/main.py` generated locally, and runs `galactic_raiders/game/`
  unchanged.

Sensor -> difficulty behavior is unchanged: the A2 photoresistor still
only eases WAVE difficulty (never boss fights), motion/mic still feed
the same hooks in `game.py` -- just computed on the PC now, since
that's where the game (and the adaptive AI reading it) actually lives.
The PC sends AI status back to the board every tick so the OLED still
updates live.

## Setup

**On your PC**, you just need the `python/` folder (which already
contains both `pc_client.py` and `galactic_raiders/` side by side --
nothing to copy or rearrange). Install the same two game deps (no
`arduino.app_utils`/`msgpack` needed here, since this script never
talks to the Bridge):
```bash
pip install pygame-ce numpy
```

**On the UNO Q**, run the board-side script from this `network/`
folder (works from a plain venv or inside App Lab -- either way, App
Lab's container already has Bridge/msgpack, and a plain venv works too
if you followed the `remote-display/README.md` setup):
```bash
python3 network/board_server.py --pc-ip <YOUR_PC_IP>
```

**On your PC**, run the game client from `python/`, pointing at the
board:
```bash
python3 python/pc_client.py --board-ip 192.168.1.22
```

Order doesn't matter much -- whichever starts first just waits for the
other's packets. If the game window opens but nothing responds to
input, double-check both IPs and that no firewall on either machine is
blocking UDP ports 5551/5552.

## Ports

- `5551` -- board -> PC, controller + sensor state (~60Hz)
- `5552` -- PC -> board, AI status (OLED) + haptic buzz requests

Both are UDP. If either port is already in use on your network, change
`CONTROL_PORT`/`STATUS_PORT` at the top of **both** files to match.

## The hardcoded PC IP (`DEFAULT_PC_IP`) -- read this if input silently stops working

`board_server.py` needs to know your PC's IP address to send
controller/sensor packets to. There are two ways it gets that:

1. **The `--pc-ip` command-line flag**, if you launch it manually
   (SSH, terminal, etc.):
   ```bash
   python3 network/board_server.py --pc-ip 192.168.1.182
   ```
2. **`DEFAULT_PC_IP`**, a constant hardcoded near the top of
   `board_server.py`, used as a fallback whenever you *don't* pass
   `--pc-ip` -- which is exactly what happens if you launch the sketch
   from **App Lab's Run button**, since there's no way to pass a flag
   there.

```python
DEFAULT_PC_IP = "192.168.1.182"  # <-- CHANGE THIS if your PC's IP changes
```

**Symptom if this value is wrong or stale:** `board_server.py` keeps
printing that it's sending packets (UDP is fire-and-forget -- it
doesn't know or care if anyone's listening at that address), and
`pc_client.py` starts up fine and prints its two startup lines, but
your joystick and buttons do *nothing* -- no errors on either side,
just silence. This is the single most common "it stopped working"
report for this project, and it's almost always a stale IP here, not
a code bug.

**Your PC's IP can change** any time DHCP renews its lease -- after a
reboot, a driver update, waking from sleep, or your router restarting.
If input that used to work suddenly stops, check this first before
anything else:

1. On your PC, run `ipconfig` (Windows) and find the **IPv4 Address**
   of whichever adapter is actually active (Ethernet or Wi-Fi).
2. Compare it against `DEFAULT_PC_IP` in `board_server.py`. If they
   don't match, that's the bug.
3. Either update `DEFAULT_PC_IP` to the new address and redeploy to
   the board, or always launch with an explicit `--pc-ip` matching
   your current address.

**To stop this from recurring**, give your PC a fixed address instead
of chasing DHCP drift -- either option works:
- Set a **DHCP reservation** for your PC's MAC address in your
  router's admin page, so it's always handed the same IP.
- Set a **static IP** directly on the PC's network adapter in Windows
  network settings.

If the IP is confirmed correct and input is still silent, the next
most likely cause is a firewall silently dropping inbound UDP on port
`5551` on the PC (common after a Windows Update resets firewall
rules) -- check that next.