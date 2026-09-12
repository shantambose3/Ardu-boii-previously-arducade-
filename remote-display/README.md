# Remote display (stream the game to your PC over WiFi)

Adds RustDesk-based screen streaming for UNO Q, so you can play/watch
Galactic Raiders on your computer without a working HDMI hookup.

## Why RustDesk (not xrdp, not VNC)

- **xrdp** is Arduino's other officially-documented option, but it spins
  up a *second* desktop session on connect, which fights the one LightDM
  already started on boot over D-Bus -- commonly shows as a black screen
  that disconnects immediately.
- **x11vnc** works but is slow (CPU-only framebuffer diffing), and its
  password field is capped at 8 characters.
- **RustDesk** attaches to the *existing* desktop session instead of
  creating a new one, and is noticeably snappier for both video and
  keyboard input.

## Quick start

```bash
scp -r remote-display arduino@<board-ip>:~/
ssh arduino@<board-ip>
chmod +x ~/remote-display/setup_rustdesk.sh
~/remote-display/setup_rustdesk.sh
```

The script will:
1. Install RustDesk.
2. Ask whether you have a real monitor attached. If not, it installs
   `xserver-xorg-video-dummy` and `10-dummy.conf` so Xorg has a virtual
   display to render into (RustDesk refuses to attach to a session with
   zero enumerable displays -- this fixes that).
3. Autostart RustDesk on login.
4. Enable lightdm autologin, so the board reaches a usable desktop with
   no monitor/keyboard attached.
5. Disable the idle screen lock (no point locking a headless board).

Then:
```bash
sudo reboot
```

After ~30-60s, open the RustDesk client on your PC (rustdesk.com) --
the board shows up automatically on the same network. First time in,
run `DISPLAY=:0 rustdesk &` on the board itself once to set a
permanent password (Settings -> Security), so you skip the one-time
code on every future connection.

## Playing the game over the stream

Once connected via RustDesk, open a terminal in the remote session:
```bash
cd ~/ArduinoApps/ardu-cade/python
python3 main.py
```

### Note: running via App Lab won't show a window

If you launch the app through Arduino App Lab (Run button / App Lab's own
terminal), it runs inside a Docker container that has no access to the
host's X11 display -- pygame silently falls back to a dummy video driver,
so the game runs (you'll see log output, Bridge/AI-status messages, audio
underrun spam, etc.) but no window ever appears, even over RustDesk.

To get an actual window, run `main.py` with a plain Python venv on the
board directly (not through App Lab), so it uses the host's real
`DISPLAY`. Full recipe, in order:

**0. Flash the sketch at least once via App Lab first.** App Lab's
**Run** button is what actually compiles + uploads `sketch/sketch.ino`
to the MCU side -- a plain venv only ever runs the *Python* side, so if
the sketch was never flashed, Bridge calls like `get_controller_state`
will fail with `method ... not available` no matter how the Python side
is launched. Open the app in App Lab and click **Run** once (you can
stop it right after -- the flash sticks even after stopping), then
switch to the venv route below for actually playing.

**1. Reach the App Lab libraries -- copy `arduino.app_utils` out of the
container.** This is the Bridge/App runtime `main.py` imports; it isn't
on PyPI, it's baked directly into App Lab's Docker image:
```bash
sudo docker ps   # find the running ardu-cade container ID
sudo docker cp <container_id>:/usr/local/lib/python3.13/site-packages/arduino /tmp/arduino_pkg
sudo cp -r /tmp/arduino_pkg ~/myenv/lib/python3.13/site-packages/arduino
```

**2. Install the rest of `python/requirements.txt`** in that same venv
(this covers `pygame-ce`/`numpy` for the game itself, plus `msgpack`,
`requests`, and `watchdog`, which `arduino.app_utils` needs internally
and which also come pre-installed in App Lab's image but not in a
plain venv):
```bash
source ~/myenv/bin/activate
cd ~/ArduinoApps/ardu-cade/python
pip install -r requirements.txt
```

**3. Run it with the display explicitly set:**
```bash
DISPLAY=:0 python3 main.py
```

Your physical D2-D5/D8-D10 buttons and joystick still work as normal --
they're wired to the MCU side via the Bridge, which RustDesk doesn't
touch. RustDesk only mirrors the display and forwards your PC's
keyboard/mouse into the session.

## Known tradeoff

This is desktop mirroring, not a dedicated low-latency game-streaming
pipeline -- expect a bit more input lag than a direct HDMI hookup.
Fine for casual play/testing; something to keep in mind if you're
chasing frame-perfect dodges on the Infinity Ray.

## Files in this folder

- `10-dummy.conf` -- Xorg dummy-display config (only used if you're
  fully headless; copied to `/etc/X11/xorg.conf.d/` by the script).
- `setup_rustdesk.sh` -- one-shot setup script, safe to re-run.
