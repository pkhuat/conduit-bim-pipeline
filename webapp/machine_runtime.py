"""Selects the SIM vs the REAL machine for the web API, and owns the single
shared real-machine instance.

    CONDUIT_MACHINE=sim   (default)  -> SimMachine, fresh per run, nothing moves.
                                        Safe on laptops and the cloud deploy.
    CONDUIT_MACHINE=real             -> the real serial-backed Machine
                                        (machine/machine_functions.py). ONE shared
                                        instance, guarded by a run-lock. Only ever
                                        set on the Raspberry Pi, next to hardware.

Both paths drive the SAME choreography (run_stick_job.run_stick); the only thing
that changes is the transport underneath.

Milestone 1 is a *safe wired test*: real motion is bounded (SAFE_MODE clamps every
feed / bend / roll to a small cap) and the angles are NOT yet calibrated — a raw
value is raw motor steps, so `bend 30` is 30 steps, not 30 degrees. Calibrated
angles + real springback are milestone 2, after a hardware-review pass with Josh.
"""

import contextlib
import os
import threading


def _flag(name, default):
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off")


MODE = os.environ.get("CONDUIT_MACHINE", "sim").strip().lower()
LIVE = MODE == "real"

# Safe wired-test guard rails (raw motor-step units, since we're uncalibrated).
SAFE_MODE = _flag("CONDUIT_MACHINE_SAFE", "1")
CAPS = {
    "advance": float(os.environ.get("CONDUIT_MAX_ADVANCE", "200")),  # per feed
    "bend": float(os.environ.get("CONDUIT_MAX_BEND", "30")),         # per bend
    "rotate": float(os.environ.get("CONDUIT_MAX_ROTATE", "90")),     # per roll
}

_run_lock = threading.Lock()   # exclusive access to the real machine for one run
_real = None                   # the shared real Machine (opens serial once)
RUN_BUSY = threading.Event()   # set while a UI bend program is running (gamepad reads it)


def is_busy():
    """True while a bend program is running — the Xbox jog loop checks this and
    stops jogging so manual and program input never fight over the motors."""
    return RUN_BUSY.is_set()


def mode_info():
    return {"mode": "real" if LIVE else "sim", "live": LIVE,
            "safe": SAFE_MODE, "caps": CAPS}


def _real_machine():
    """The one real Machine instance. Opening it binds the serial ports and starts
    the fault-poll thread, so we do it once and share it."""
    global _real
    if _real is None:
        from machine.machine_functions import Machine
        _real = Machine()
    return _real


@contextlib.contextmanager
def acquire():
    """Yield a machine to drive one run.

    Live: the shared real Machine, held under the run-lock so two requests can't
    interleave commands on the same serial port. Sim: a throwaway SimMachine."""
    if LIVE:
        with _run_lock:
            RUN_BUSY.set()          # tell the gamepad loop to hold off
            try:
                yield _real_machine(), True
            finally:
                RUN_BUSY.clear()
    else:
        from machine.sim_machine import SimMachine
        yield SimMachine(verbose=False), False


def peek_real():
    """The shared real Machine for out-of-band commands (estop / status), or None
    in sim mode. Does NOT take the run-lock — estop must never wait on a run."""
    return _real_machine() if LIVE else None


@contextlib.contextmanager
def record(machine):
    """Capture every firmware command + reply a run sends, for either transport.

    Wraps the machine's send / send_and_wait methods for the duration of the run.
    run_stick issues all its moves through send_and_wait; jogs (send) aren't used
    by the choreography but are captured too for completeness."""
    log = []

    def wrap(orig, board, expect_reply):
        def inner(cmd):
            resp = orig(cmd)
            log.append({"board": board, "cmd": cmd,
                        "response": resp if expect_reply else "OK"})
            return resp
        return inner

    saved = {}
    for name, board, reply in (("send", 1, False), ("send_and_wait", 1, True),
                               ("send2", 2, False), ("send_and_wait2", 2, True)):
        if hasattr(machine, name):
            saved[name] = getattr(machine, name)
            setattr(machine, name, wrap(saved[name], board, reply))
    try:
        yield log
    finally:
        for name, orig in saved.items():
            # these were class methods; drop the per-instance override we added
            machine.__dict__.pop(name, None)


def clamp_bends(bends):
    """In SAFE_MODE, clamp each bend's feed / roll / angle to the caps so a first
    live run can only make small, recoverable motions. Returns (bends, clamped)."""
    if not SAFE_MODE:
        return bends, False
    out = []
    clamped = False

    def cap(v, limit):
        nonlocal clamped
        c = max(-limit, min(limit, v))
        if c != v:
            clamped = True
        return c

    for b in bends:
        nb = dict(b)
        nb["advance"] = cap(float(b.get("advance") or 0), CAPS["advance"])
        nb["rotate"] = cap(float(b.get("rotate") or 0), CAPS["rotate"])
        nb["angle"] = cap(float(b.get("angle") or 0), CAPS["bend"])
        out.append(nb)
    return out, clamped


def final_state(machine):
    """Best-effort axis snapshot for the UI. SimMachine tracks positions; the real
    Machine doesn't, so we report which axes it has enabled."""
    axes = getattr(machine, "axes", None)
    if isinstance(axes, dict):   # SimMachine
        return {n: {"position": round(ax["position"], 2), "enabled": ax["enabled"]}
                for n, ax in axes.items()}
    enabled = getattr(machine, "_enabled", set())   # real Machine
    return {n: {"position": None, "enabled": n in enabled}
            for n in ("ADVANCE", "ROTATE", "BEND", "SQUEEZE", "CHUCK")}
