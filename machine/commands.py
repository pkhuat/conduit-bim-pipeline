"""ClearCore command interface — the protocol vocabulary the machine speaks.

Each high-level method builds a firmware command STRING and hands it to a
transport (send / send_and_wait for board 1, send2 / send_and_wait2 for board 2).
This base owns only the command grammar; a subclass supplies the transport:

  - SimMachine (machine/sim_machine.py) — a software model of the firmware, so the
    pipeline can be exercised end to end with no hardware.
  - a real serial-backed machine — supplied separately; on the shared machine repo
    the driver can import that richer class instead (real serial + fault polling).

The grammar mirrors the ClearCore firmware's own command parser (ADVANCE TO x,
BEND ENABLE, SQUEEZE CLOSE, CHUCK JOG v, ...). Written to that protocol, not copied
from any hardware-side implementation.
"""


class Machine:
    BOARD1_AXES = ("ADVANCE", "ROTATE", "BEND", "SQUEEZE")
    BOARD2_AXES = ("CHUCK",)

    def __init__(self):
        self._enabled = set()          # board-1 axes currently enabled

    # ── transport (a subclass provides these) ──────────────────────────────────
    def send(self, cmd):            raise NotImplementedError
    def send_and_wait(self, cmd):   raise NotImplementedError
    def send2(self, cmd):           raise NotImplementedError
    def send_and_wait2(self, cmd):  raise NotImplementedError

    # ── generic board-1 axis verbs (ADVANCE / ROTATE / BEND) ───────────────────
    def _enable(self, axis):
        resp = self.send_and_wait(f"{axis} ENABLE")
        if "OK" in resp:
            self._enabled.add(axis)
        return resp

    def _disable(self, axis):
        resp = self.send_and_wait(f"{axis} DISABLE")
        self._enabled.discard(axis)
        return resp

    def _to(self, axis, value):  return self.send_and_wait(f"{axis} TO {value}")
    def _by(self, axis, value):  return self.send_and_wait(f"{axis} BY {value}")
    def _jog(self, axis, value): return self.send(f"{axis} JOG {value}")
    def _home(self, axis):       return self.send_and_wait(f"{axis} HOME")

    # ── ADVANCE ────────────────────────────────────────────────────────────────
    def advance_enable(self):  return self._enable("ADVANCE")
    def advance_disable(self): return self._disable("ADVANCE")
    def advance_to(self, v):   return self._to("ADVANCE", v)
    def advance_by(self, v):   return self._by("ADVANCE", v)
    def advance_jog(self, v):  return self._jog("ADVANCE", v)
    def advance_home(self):    return self._home("ADVANCE")

    # ── ROTATE ─────────────────────────────────────────────────────────────────
    def rotate_enable(self):   return self._enable("ROTATE")
    def rotate_disable(self):  return self._disable("ROTATE")
    def rotate_to(self, v):    return self._to("ROTATE", v)
    def rotate_by(self, v):    return self._by("ROTATE", v)
    def rotate_jog(self, v):   return self._jog("ROTATE", v)
    def rotate_home(self):     return self._home("ROTATE")

    # ── BEND ───────────────────────────────────────────────────────────────────
    def bend_enable(self):     return self._enable("BEND")
    def bend_disable(self):    return self._disable("BEND")
    def bend_to(self, v):      return self._to("BEND", v)
    def bend_by(self, v):      return self._by("BEND", v)
    def bend_jog(self, v):     return self._jog("BEND", v)
    def bend_home(self):       return self._home("BEND")

    # ── SQUEEZE (open/close rollers, board 1) ──────────────────────────────────
    def squeeze_enable(self):  return self._enable("SQUEEZE")
    def squeeze_disable(self): return self._disable("SQUEEZE")
    def squeeze_open(self):    return self.send_and_wait("SQUEEZE OPEN")
    def squeeze_close(self):   return self.send_and_wait("SQUEEZE CLOSE")
    def squeeze_jog(self, v):  return self.send(f"SQUEEZE JOG {v}")

    # ── CHUCK (board 2, velocity-controlled) ───────────────────────────────────
    def chuck_enable(self):    return self.send_and_wait2("CHUCK ENABLE")
    def chuck_disable(self):   return self.send_and_wait2("CHUCK DISABLE")
    def chuck_jog(self, v):    return self.send2(f"CHUCK JOG {v}")

    # ── status / safety ────────────────────────────────────────────────────────
    def status(self, axis):    return self.send_and_wait(f"STATUS {axis}")
    def zero(self, axis):      return self.send_and_wait(f"ZERO {axis}")
    def ping(self):            return self.send_and_wait("PING")
    def estop(self):           return self.send("ESTOP")
