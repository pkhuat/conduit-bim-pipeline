"""Simulated machine for safe development and demos.

SimMachine has the exact same interface as machine.commands.Machine,
but it never opens a serial port, so nothing physical can ever move.

How it works: Machine's high-level methods (advance_to, bend_jog, ...) build
protocol strings and hand them to send / send_and_wait. SimMachine inherits
those methods unchanged and replaces only the transport layer — instead of
writing to /dev/ttyACM0 and /dev/ttyACM1, commands go to a software model of
the firmware that mirrors the parsers in clearcore/. Programs therefore
exercise the same command grammar in simulation as on the real machine,
including firmware error replies for commands the firmware doesn't support.

Intentional differences from the real firmware:
- Moves complete instantly; STATUS reports MOVING only while a jog is active.
- ENCODER READ returns the tracked axis position (real firmware stubs 0).
- HOME sets position to 0 (real firmware replies OK MOVING but does nothing).
- Commands that would move a disabled axis are recorded in self.warnings —
  a real ClearPath motor stays still when disabled, but the firmware still
  replies OK, so this class of program bug is invisible on hardware logs.
"""

import threading

from machine.commands import Machine


class SimMachine(Machine):
    BOARD1_AXES = ("ADVANCE", "ROTATE", "BEND", "SQUEEZE")
    BOARD2_AXES = ("CHUCK",)

    def __init__(self, verbose=True):
        # Deliberately does NOT call Machine.__init__ — no serial ports opened, no
        # log file created, no fault-poll thread started. But mirror the plain state
        # Machine.__init__ sets up, since the inherited high-level methods use it
        # (e.g. enable/disable track self._enabled; log() guards on self._log_file).
        self.ser = None
        self.ser2 = None
        self._lock = threading.Lock()
        self._enabled = set()   # CC1 motors currently enabled (BEND/ROTATE/ADVANCE/SQUEEZE)
        self._polling = False   # no real fault-poll loop in the sim
        self._log_file = None   # log() prints but writes to no file
        self.verbose = verbose
        self.history = []   # (board, command, response) for every command sent
        self.warnings = []  # suspicious-but-accepted commands, e.g. moving a disabled axis
        self.axes = {
            name: {"position": 0.0, "enabled": False, "jog_speed": 0.0}
            for name in self.BOARD1_AXES + self.BOARD2_AXES
        }
        if self.verbose:
            print("[SIM] SimMachine ready — no serial ports opened, no hardware can move")

    # ─────────────────────────────────────────────────────────────────────────
    # TRANSPORT LAYER — replaces serial I/O from Machine
    # ─────────────────────────────────────────────────────────────────────────

    def send(self, cmd):
        self._transact(1, cmd)

    def send_and_wait(self, cmd):
        return self._transact(1, cmd)

    def send2(self, cmd):
        self._transact(2, cmd)

    def send_and_wait2(self, cmd):
        return self._transact(2, cmd)

    def _transact(self, board, cmd):
        response = self._firmware(board, cmd)
        self.history.append((board, cmd, response))
        if self.verbose:
            arrow = ">>>" if board == 1 else ">>2"
            print(f"[SIM] {arrow} {cmd:<24} -> {response}")
        return response

    # ─────────────────────────────────────────────────────────────────────────
    # SIMULATED FIRMWARE — mirrors the parsers in clearcore/*.ino
    # ─────────────────────────────────────────────────────────────────────────

    def _firmware(self, board, cmd):
        parts = cmd.split()
        if not parts:
            return "ERR UNKNOWN_CMD empty command received"
        subsystem = parts[0]
        action = parts[1] if len(parts) > 1 else None
        value = parts[2] if len(parts) > 2 else None

        if subsystem == "PING":
            return "OK"

        if subsystem == "ESTOP":
            # Each board only stops its own motors — exactly like the firmware.
            # Note: Machine.estop() only sends to board 1, so a chuck jog
            # survives it. See README "Safety notes".
            targets = self.BOARD1_AXES if board == 1 else self.BOARD2_AXES
            for name in targets:
                self.axes[name]["jog_speed"] = 0.0
            return "OK"

        if subsystem == "STATUS":
            return self._status(board, action)

        if subsystem == "ZERO":
            return self._zero(board, action)

        if board == 1:
            if subsystem in ("ADVANCE", "ROTATE", "BEND"):
                return self._axis_cmd(subsystem, action, value)
            if subsystem == "SQUEEZE":
                return self._squeeze_cmd(action)
            if subsystem == "CHUCK":
                return self._chuck_board1_cmd(action)
            if subsystem == "ENCODER":
                return self._encoder_cmd(value)
        else:
            if subsystem == "CHUCK":
                return self._chuck_board2_cmd(action, value)

        return f"ERR UNKNOWN_CMD {subsystem}"

    def _axis_cmd(self, name, action, value):
        """ADVANCE / ROTATE / BEND on board 1 (SD-series, step & direction)."""
        ax = self.axes[name]
        if action is None:
            return f"ERR BAD_VALUE {name} action missing"
        if action == "ENABLE":
            ax["enabled"] = True
            ax["jog_speed"] = 0.0  # firmware does MoveStopAbrupt on enable
            return "OK"
        if action == "DISABLE":
            ax["enabled"] = False
            ax["jog_speed"] = 0.0
            return "OK"
        if action in ("TO", "BY"):
            if value is None:
                return f"ERR BAD_VALUE {name} {action} value missing"
            target = self._to_number(value)
            if not ax["enabled"]:
                self._warn(f"{name} {action} {value} while {name} is DISABLED — real motor would not move")
            if action == "TO":
                ax["position"] = target
            else:
                ax["position"] += target
            return "OK MOVING"
        if action == "JOG":
            if value is None:
                return f"ERR BAD_VALUE {name} JOG value missing"
            speed = self._to_number(value)
            if speed != 0 and not ax["enabled"]:
                self._warn(f"{name} JOG {value} while {name} is DISABLED — real motor would not move")
            ax["jog_speed"] = speed
            return "OK"
        if action == "HOME":
            ax["position"] = 0.0
            return "OK MOVING"
        return f"ERR UNKNOWN_CMD {name} {action}"

    def _squeeze_cmd(self, action):
        """SQUEEZE on board 1. NOTE: the firmware has no JOG case here — the
        sim mirrors that and returns ERR, which is how this mismatch with
        Machine.squeeze_jog() / the Xbox triggers was found."""
        ax = self.axes["SQUEEZE"]
        if action is None:
            return "ERR BAD_VALUE SQUEEZE action missing"
        if action == "ENABLE":
            ax["enabled"] = True
            return "OK"
        if action == "DISABLE":
            ax["enabled"] = False
            return "OK"
        if action == "OPEN":
            if not ax["enabled"]:
                self._warn("SQUEEZE OPEN while SQUEEZE is DISABLED — real motor would not move")
            ax["position"] -= 5000  # firmware's uncalibrated placeholder step count
            return "OK"
        if action == "CLOSE":
            if not ax["enabled"]:
                self._warn("SQUEEZE CLOSE while SQUEEZE is DISABLED — real motor would not move")
            ax["position"] += 5000
            return "OK"
        return f"ERR UNKNOWN_CMD SQUEEZE {action}"

    def _chuck_board1_cmd(self, action):
        """CHUCK on board 1 is a do-nothing placeholder in the firmware
        (the real chuck lives on board 2). Mirrored faithfully."""
        if action is None:
            return "ERR BAD_VALUE CHUCK action missing"
        if action in ("CLOSE", "OPEN", "ENABLE", "DISABLE"):
            return "OK"
        return f"ERR UNKNOWN_CMD CHUCK {action}"

    def _chuck_board2_cmd(self, action, value):
        """CHUCK on board 2 (MC-series, PWM velocity control)."""
        ax = self.axes["CHUCK"]
        if action is None:
            return "ERR BAD_VALUE CHUCK action missing"
        if action == "ENABLE":
            ax["enabled"] = True
            return "OK"
        if action == "DISABLE":
            ax["enabled"] = False
            ax["jog_speed"] = 0.0
            return "OK"
        if action == "JOG":
            if value is None:
                return "ERR BAD_VALUE CHUCK JOG value missing"
            speed = self._to_number(value)
            if speed != 0 and not ax["enabled"]:
                self._warn(f"CHUCK JOG {value} while CHUCK is DISABLED — real motor would not move")
            ax["jog_speed"] = speed
            return "OK"
        return f"ERR UNKNOWN_CMD CHUCK {action}"

    def _encoder_cmd(self, target):
        """ENCODER READ <target> on board 1. Real firmware stubs 0; the sim
        returns tracked positions so UI work has live numbers to display.
        CONDUIT maps to the advance position (conduit feed length)."""
        if target in ("ADVANCE", "SQUEEZE"):
            return f"OK {self.axes[target]['position']:g}"
        if target == "CONDUIT":
            return f"OK {self.axes['ADVANCE']['position']:g}"
        return f"ERR UNKNOWN_CMD ENCODER READ {target}"

    def _status(self, board, axis):
        if axis is None:
            return "ERR BAD_VALUE STATUS axis missing"
        valid = self.BOARD1_AXES if board == 1 else self.BOARD2_AXES
        if axis not in valid:
            return f"ERR UNKNOWN_CMD STATUS {axis}"
        # Mirror the firmware's reply, which carries commanded position + torque
        # (OK <state> torque=..% pos=..) so the live twin reads the sim the same way.
        state = "MOVING" if self.axes[axis]["jog_speed"] != 0 else "IDLE"
        return f"OK {state} torque=0% pos={int(round(self.axes[axis]['position']))}"

    def _zero(self, board, axis):
        if axis is None:
            return "ERR BAD_VALUE ZERO axis missing"
        if board == 1 and axis in self.BOARD1_AXES:
            self.axes[axis]["position"] = 0.0
            return "OK"
        if board == 2 and axis == "CHUCK":
            # MCVC is velocity-controlled — no position reference to zero
            return "OK"
        return f"ERR UNKNOWN_CMD ZERO {axis}"

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_number(value):
        # atol/atof in the firmware silently yield 0 on garbage; mirror that
        try:
            return float(value)
        except ValueError:
            return 0.0

    def _warn(self, msg):
        self.warnings.append(msg)
        if self.verbose:
            print(f"[SIM][WARN] {msg}")

    def summary(self):
        lines = ["[SIM] Final state:"]
        for name in self.BOARD1_AXES + self.BOARD2_AXES:
            ax = self.axes[name]
            lines.append(
                f"  {name:<8} pos={ax['position']:>8g}   "
                f"enabled={str(ax['enabled']):<5}   jog={ax['jog_speed']:g}"
            )
        if self.warnings:
            lines.append(f"[SIM] {len(self.warnings)} warning(s):")
            lines.extend(f"  - {w}" for w in self.warnings)
        else:
            lines.append("[SIM] No warnings.")
        return "\n".join(lines)
