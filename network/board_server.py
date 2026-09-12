"""
Cyber Deck -- UNO Q side, "controller server" mode.

Use this INSTEAD of python/main.py when you want the actual game
(pygame rendering, adaptive AI, everything in galactic_raiders/game/)
to run on a more powerful PC, while the UNO Q just relays real
hardware input/sensors to it over the network.

This still talks to sketch/sketch.ino exactly like python/main.py does
(same Bridge calls, same field names) -- only the destination of that
data changes: instead of turning it into local pygame key events, it's
packed into JSON and sent over UDP to pc_client.py running on your PC.

It also listens for a small amount of traffic coming back the other
way (AI status for the OLED, haptic buzz requests for the D6/D7
motors) and forwards those to the sketch, same Bridge calls
python/main.py used to make locally.

Run this on the UNO Q (works both inside App Lab's container -- Bridge
access is what App Lab actually provides -- and in a plain venv):

    python3 board_server.py --pc-ip 192.168.1.50

`--pc-ip` is your gaming PC's IP address on the same network. Ports
are fixed below (CONTROL_PORT / STATUS_PORT) -- change both here and
in pc_client.py together if you need different ones (e.g. already in
use).
"""

import argparse
import json
import socket
import threading
import time

from arduino.app_utils import App, Bridge

CONTROL_PORT = 5551   # board -> PC: controller + sensor state, ~60Hz
STATUS_PORT = 5552    # PC -> board: AI status (OLED) + haptic buzzes

SEND_HZ = 60

# Hardcoded default so you can just hit Run in App Lab without typing a
# flag every time. CHANGE THIS to your PC's IP if it changes (check
# with `ipconfig` on Windows / `ip addr` on Mac/Linux). Still
# overridable with --pc-ip on the command line.
DEFAULT_PC_IP = "192.168.1.182"


def build_control_packet():
    """One Bridge round-trip per tick, same call python/main.py makes.
    Returns None if the MCU isn't ready yet (e.g. still booting)."""
    try:
        rpc = Bridge.call("get_controller_state")
        data = rpc.result() if hasattr(rpc, "result") else rpc
    except Exception:
        return None
    if not data:
        return None
    return {
        "type": "controller_state",
        "buttons": data.get("buttons", 0),
        "layerButtons": data.get("layerButtons", 0),
        "sleepWake": bool(data.get("sleepWake", False)),
        "joyX": data.get("joyX", 0),
        "joyY": data.get("joyY", 0),
        "lightLevel": data.get("lightLevel", 0),
        "micLevel": data.get("micLevel", 0),
        "accelX": data.get("accelX", 0),
        "accelY": data.get("accelY", 0),
        "accelZ": data.get("accelZ", 0),
        "mpuOk": bool(data.get("mpuOk", False)),
    }


def send_loop(sock, pc_addr):
    """Runs as App.run()'s user_loop -- once per tick, poll the sketch
    and forward it to the PC. Matches the ~60Hz cadence python/main.py
    used for its local _bridge_loop."""
    packet = build_control_packet()
    if packet is not None:
        try:
            sock.sendto(json.dumps(packet).encode("utf-8"), pc_addr)
        except OSError:
            pass  # network hiccup -- just skip this tick
    time.sleep(1.0 / SEND_HZ)


def recv_loop(sock):
    """Background thread: listens for AI-status / haptic messages sent
    back from pc_client.py and forwards them to the sketch, same calls
    python/main.py's push_ai_status()/HapticsBridge.tick() used to
    make locally."""
    sock.bind(("0.0.0.0", STATUS_PORT))
    while True:
        try:
            raw, _addr = sock.recvfrom(4096)
            msg = json.loads(raw.decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        msg_type = msg.get("type")
        try:
            if msg_type == "ai_status":
                Bridge.call(
                    "set_ai_status",
                    msg["learning_pct"],
                    min(msg["samples"], 65535),
                    msg["favorite_weapon"],
                    msg["aggression_pct"],
                    msg["fatigue_ease_pct"],
                )
            elif msg_type == "haptic":
                Bridge.call("trigger_vibration", msg["motor"], msg["duration_ms"])
        except Exception:
            pass  # skip this message rather than crash the loop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pc-ip", default=DEFAULT_PC_IP,
        help=f"IP address of the PC running pc_client.py (default: {DEFAULT_PC_IP})",
    )
    args = parser.parse_args()
    pc_addr = (args.pc_ip, CONTROL_PORT)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    threading.Thread(target=recv_loop, args=(recv_sock,), daemon=True).start()

    print(f"[board_server] streaming controller state to {args.pc_ip}:{CONTROL_PORT}")
    print(f"[board_server] listening for AI status / haptics on :{STATUS_PORT}")

    # App.run() starts the UNO Q Bridge runtime and calls user_loop on
    # its own schedule -- no pygame here, so no need for a separate
    # thread the way python/main.py needed one to free up the main
    # thread for pygame's event loop.
    App.run(user_loop=lambda: send_loop(send_sock, pc_addr))


if __name__ == "__main__":
    main()
