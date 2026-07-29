"""Runs Josh's Xbox jog loop INSIDE the webapp, on the one shared real Machine, so
manual gamepad control and the UI's bend programs drive the same ClearCore without
fighting over the serial port.

Real mode only. Degrades cleanly (no pygame, no controller, or sim mode) so it can
never break the API — the New bend tab just shows manual control as unavailable.
"""

import os
import threading

import machine_runtime as _mach

# A headless Pi has no display; SDL still needs a (dummy) video driver for joystick
# input. Don't override an explicit choice.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

_thread = None
_stop = None
_lock = threading.Lock()
_state = {"running": False, "controller": None, "error": None}


def available():
    """(ok, info): can we jog here, and the controller name — or the reason not.
    Never probes the joystick while the loop owns it (that would break the loop)."""
    if not _mach.LIVE:
        return False, "Simulation mode — no real machine to jog."
    try:
        import pygame
    except Exception:
        return False, "pygame not installed on the Pi (pip install pygame)."
    try:
        pygame.init()
        pygame.joystick.init()
        n = pygame.joystick.get_count()
        name = pygame.joystick.Joystick(0).get_name() if n else None
        pygame.joystick.quit()
    except Exception as e:
        return False, f"controller probe failed: {e}"
    if not n:
        return False, "No Xbox controller detected."
    return True, name


def status():
    with _lock:
        running = _state["running"]
        ctrl = _state["controller"]
        err = _state["error"]
    if running:   # loop owns the joystick — report state without re-probing it
        return {"live": _mach.LIVE, "available": True, "controller": ctrl,
                "reason": None, "running": True, "error": err}
    ok, info = available()
    return {"live": _mach.LIVE, "available": ok, "controller": info if ok else None,
            "reason": None if ok else info, "running": False, "error": err}


def _run():
    from xbox_control.xbox_controller import run_controller
    try:
        run_controller(_mach.peek_real(), stop_event=_stop, is_busy=_mach.is_busy, verbose=True)
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False


def start():
    global _thread, _stop
    with _lock:
        if _state["running"]:
            return {"ok": True, "running": True, "note": "already running"}
    ok, info = available()
    if not ok:
        return {"ok": False, "error": info}
    _stop = threading.Event()
    with _lock:
        _state.update(running=True, controller=info, error=None)
    _thread = threading.Thread(target=_run, daemon=True, name="xbox-jog")
    _thread.start()
    return {"ok": True, "running": True, "controller": info}


def stop():
    global _stop
    if _stop is not None:
        _stop.set()
    with _lock:
        _state["running"] = False
    return {"ok": True, "running": False}
