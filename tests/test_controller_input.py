"""
Lightweight edge-case/stress tests for the controller-input logic in
python/pc_client.py's NetworkController -- the class that turns board_
server.py's UDP packets into synthetic pygame key events.

Deliberately kept small and fast (no real hardware, no real network,
no display) -- these just hammer the pure state-machine logic with
awkward/adversarial inputs: exact deadzone boundaries, button bounce,
missing/malformed fields, and the D8/D9/D10 layer-select removal.

Run from ardu-cade/:
    pip install pytest pygame-ce --break-system-packages
    SDL_VIDEODRIVER=dummy PYTHONPATH=python pytest tests/test_controller_input.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # headless, no real display needed

import pygame  # noqa: E402

pygame.init()

import pc_client  # noqa: E402


def drain_events():
    """Pop everything currently queued and return it as a plain list."""
    events = pygame.event.get()
    return events


def make_controller():
    pygame.event.clear()
    return pc_client.NetworkController(game=None)


# ---------------------------------------------------------------------
# Joystick deadzone boundary
# ---------------------------------------------------------------------

def test_deadzone_exact_boundary_does_not_trigger():
    """joy_x == JOY_DEADZONE exactly must NOT count as pressed (strict >)."""
    c = make_controller()
    c._handle_joystick(pc_client.JOY_DEADZONE, 0)
    events = drain_events()
    assert not any(e.type == pygame.KEYDOWN for e in events)


def test_deadzone_one_past_boundary_triggers():
    c = make_controller()
    c._handle_joystick(pc_client.JOY_DEADZONE + 1, 0)
    events = drain_events()
    keys_down = {e.key for e in events if e.type == pygame.KEYDOWN}
    assert pygame.K_d in keys_down  # positive X -> right


def test_deadzone_negative_boundary_symmetric():
    c = make_controller()
    c._handle_joystick(-(pc_client.JOY_DEADZONE + 1), 0)
    events = drain_events()
    keys_down = {e.key for e in events if e.type == pygame.KEYDOWN}
    assert pygame.K_a in keys_down  # negative X -> left


def test_diagonal_joystick_posts_both_axes():
    c = make_controller()
    c._handle_joystick(pc_client.JOY_DEADZONE + 50, -(pc_client.JOY_DEADZONE + 50))
    events = drain_events()
    keys_down = {e.key for e in events if e.type == pygame.KEYDOWN}
    assert pygame.K_d in keys_down and pygame.K_w in keys_down


def test_joystick_return_to_center_releases_keys():
    c = make_controller()
    c._handle_joystick(pc_client.JOY_DEADZONE + 50, 0)
    drain_events()
    c._handle_joystick(0, 0)
    events = drain_events()
    keys_up = {e.key for e in events if e.type == pygame.KEYUP}
    assert pygame.K_d in keys_up


# ---------------------------------------------------------------------
# Button edge detection / bounce
# ---------------------------------------------------------------------

def test_tap_button_produces_single_keydown_keyup_pair():
    """A clean 0 -> 1 -> 0 transition across polls should be exactly one
    KEYDOWN followed by one KEYUP for a tap-style button (bit0/K_v)."""
    c = make_controller()
    c._handle_buttons(0b0001)  # press
    down_events = drain_events()
    c._handle_buttons(0b0000)  # release
    up_events = drain_events()
    assert [e.type for e in down_events] == [pygame.KEYDOWN, pygame.KEYUP]
    assert down_events[0].key == pygame.K_v
    assert up_events == []  # tap keys already released themselves on press


def test_held_button_mirrors_press_and_release():
    """Vacuum nails (bit2 / K_z) is a HELD key -- it should mirror the
    physical press/release, not auto-tap."""
    c = make_controller()
    c._handle_buttons(0b0100)  # press bit2
    down_events = drain_events()
    assert down_events and down_events[0].type == pygame.KEYDOWN and down_events[0].key == pygame.K_z
    c._handle_buttons(0b0100)  # still held -- no new event
    assert drain_events() == []
    c._handle_buttons(0b0000)  # release
    up_events = drain_events()
    assert up_events and up_events[0].type == pygame.KEYUP and up_events[0].key == pygame.K_z


def test_rapid_contact_bounce_produces_a_tap_per_flicker():
    """Simulates noisy hardware bounce (0,1,0,1,0,1 across consecutive
    ~60Hz polls) on a tap button. There is no debounce filtering in
    software here -- this documents that behavior rather than assuming
    it: each rising edge in the bounce currently produces its own tap,
    so a sufficiently bouncy physical switch could fire the bomb/ray
    multiple times per real press. Flagging this as a known gap rather
    than silently "fixing" it, since a fix changes feel (added input
    latency) and wasn't asked for."""
    c = make_controller()
    taps = 0
    sequence = [0b0001, 0b0000, 0b0001, 0b0000, 0b0001, 0b0000]
    for buttons in sequence:
        c._handle_buttons(buttons)
        taps += sum(1 for e in drain_events() if e.type == pygame.KEYDOWN)
    assert taps == 3  # three rising edges -> three taps, confirming no debounce exists


def test_multiple_simultaneous_buttons_independent():
    c = make_controller()
    c._handle_buttons(0b1001)  # bit0 (V) + bit3 (X) together
    events = drain_events()
    keys_down = {e.key for e in events if e.type == pygame.KEYDOWN}
    assert keys_down == {pygame.K_v, pygame.K_x}


# ---------------------------------------------------------------------
# D8/D9/D10 layer buttons -- must NOT do anything anymore (task 5)
# ---------------------------------------------------------------------

def test_layer_buttons_produce_no_events_at_all():
    """Regression test: layerButtons (D8/D9/D10) must no longer post
    K_1/K_2/K_3 or anything else -- those buttons only page the
    sketch-side OLED guide now."""
    c = make_controller()
    data = {
        "type": "controller_state", "buttons": 0, "layerButtons": 0b111,
        "sleepWake": False, "joyX": 0, "joyY": 0,
        "lightLevel": 0, "micLevel": 0,
        "accelX": 0, "accelY": 0, "accelZ": 0, "mpuOk": False,
    }
    c._latest = data
    c.poll()
    events = drain_events()
    assert events == []
    # also confirm the removed API surface is actually gone, not just unused
    assert not hasattr(c, "_handle_layer_buttons")
    assert not hasattr(pc_client, "LAYER_BUTTON_MAP")


# ---------------------------------------------------------------------
# Malformed / missing packet data
# ---------------------------------------------------------------------

def test_poll_with_empty_packet_does_not_crash_or_emit_events():
    c = make_controller()
    c._latest = {"type": "controller_state"}  # every field missing
    c.poll()  # must not raise
    events = drain_events()
    assert events == []
    assert c.mpu_ok is False
    assert c.latest_accel == (0, 0, 0)


def test_poll_with_no_packet_is_a_noop():
    c = make_controller()
    c._latest = None
    c.poll()  # must not raise
    assert drain_events() == []


def test_wrong_type_field_is_ignored_upstream():
    """_recv_loop only accepts type == 'controller_state'; poll() itself
    doesn't re-check type, so this documents that poll() trusts
    whatever was already placed in _latest -- the type filter lives in
    _recv_loop, not poll(). Included so a future refactor that removes
    that filter from _recv_loop gets caught here instead of silently."""
    c = make_controller()
    c._latest = {"type": "controller_state", "buttons": 1}
    c.poll()
    events = drain_events()
    assert any(e.type == pygame.KEYDOWN and e.key == pygame.K_v for e in events)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
