"""Live digital twin: reconstruct the conduit shape from the machine's real axis
positions as the operator jogs by hand.

The firmware's STATUS reply already reports each axis's commanded step position
(`pos=`). Polling ADVANCE / BEND / ROTATE and converting steps -> mm/degrees with
the calibration gives us feed length, bend angle, and roll live. This module turns
that stream of positions into a growing conduit centerline the 3-D viewer can draw
— so the pipe forms on screen as it forms on the machine.

Model (clamp-independent, peak-detected so it works however the operator jogs):
- feed increases        -> extend the straight currently being fed
- bend rises then falls  -> a bend of the PEAK angle is locked in at that point
- roll (rotate) between bends sets the next bend's plane
The bend still forming is shown live as the last segment before it's committed.

Reconstruction is unit-tested (test_live_twin.py); the position source is the real
firmware on the Pi (or SimMachine, which now mirrors the same `pos=` format).
"""

import math
import re

BEND_MIN_DEG = 3.0     # below this a bend doesn't count (noise / arm centering)
RELEASE_DEG = 8.0      # bend is "released" once it drops back under this
HYST_DEG = 5.0         # ...and has fallen this far from its peak — then we commit it

_POS = re.compile(r"pos=(-?\d+)")
_TRQ = re.compile(r"torque=(-?\d+)")


def parse_status(line):
    """Pull state / commanded position / torque out of a STATUS reply, e.g.
    'OK MOVING torque=12% pos=390140' -> {'state':'MOVING','pos':390140,'torque':12}."""
    parts = (line or "").split()
    state = parts[1] if len(parts) > 1 and parts[0] == "OK" else (parts[0] if parts else "")
    m = _POS.search(line or "")
    t = _TRQ.search(line or "")
    return {"state": state, "pos": int(m.group(1)) if m else None,
            "torque": int(t.group(1)) if t else None}


# ── centerline geometry (shared shape math with the manual bend diagram) ──────
def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _rot(v, axis, deg):                          # Rodrigues rotation
    th = math.radians(deg); c = math.cos(th); s = math.sin(th); ax = _unit(axis)
    d = v[0] * ax[0] + v[1] * ax[1] + v[2] * ax[2]; cr = _cross(ax, v)
    return tuple(v[i] * c + cr[i] * s + ax[i] * d * (1 - c) for i in range(3))


def build_centerline(triples, tail_mm=152.4):
    """(advance, angle, rotate, roll_dir) triples -> {verts, angles, cuts}.
    Same construction as the hand-bend diagram, so live and programmed shapes match."""
    p = (0.0, 0.0, 0.0); d = (1.0, 0.0, 0.0); m1 = (0.0, 0.0, 1.0); m2 = _cross(d, m1)
    verts = [p]; angles = []
    for t in triples:
        dist = max(0.0, float(t.get("advance") or 0.0))
        p = tuple(p[i] + d[i] * dist for i in range(3)); verts.append(p)
        roll = float(t.get("rotate") or 0.0) * (t.get("roll_dir") or 0)
        if roll:
            m1 = _rot(m1, d, roll); m2 = _rot(m2, d, roll)
        ang = float(t.get("angle") or 0.0)
        if ang:
            d = _rot(d, m2, ang); m1 = _rot(m1, m2, ang)
        angles.append(round(ang, 1))
    p = tuple(p[i] + d[i] * tail_mm for i in range(3)); verts.append(p)   # tail so the end shows
    STICK = 3048.0
    cum = [0.0]
    for i in range(len(verts) - 1):
        cum.append(cum[-1] + math.dist(verts[i], verts[i + 1]))
    cuts = []
    k = 1
    while k * STICK < cum[-1] - 25.0:
        cuts.append(round(k * STICK, 1)); k += 1
    return {"verts": [[round(c, 1) for c in v] for v in verts], "angles": angles, "cuts": cuts}


class LiveTwin:
    """Accumulates a conduit centerline from the live (feed_mm, bend_deg, roll_deg)
    stream. One per machine session; reset() on 'Zero & start'."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.committed = []          # locked-in bends: (advance, angle, rotate, roll_dir)
        self.pending_straight = 0.0  # mm fed since the last committed bend
        self.pending_roll = 0.0      # net roll deg since the last committed bend
        self.peak = 0.0              # peak bend deg in the bend currently forming
        self.prev = None             # (feed_mm, roll_deg) from the previous sample

    def _pending_triple(self, angle):
        return {"advance": round(self.pending_straight, 1), "angle": round(angle, 1),
                "rotate": round(abs(self.pending_roll), 1),
                "roll_dir": 1 if self.pending_roll > 0 else -1 if self.pending_roll < 0 else 0}

    def update(self, feed_mm, bend_deg, roll_deg):
        """Fold one live sample in; returns the current snapshot (readouts + path)."""
        if self.prev is not None:
            pf, pr = self.prev
            dfeed = feed_mm - pf
            if dfeed > 0:
                self.pending_straight += dfeed
            self.pending_roll += (roll_deg - pr)
            if bend_deg > self.peak:
                self.peak = bend_deg
            # a bend that rose past the threshold and has now fallen back is permanent
            if self.peak >= BEND_MIN_DEG and bend_deg <= RELEASE_DEG and bend_deg <= self.peak - HYST_DEG:
                self.committed.append(self._pending_triple(self.peak))
                self.pending_straight = 0.0
                self.pending_roll = 0.0
                self.peak = 0.0
        self.prev = (feed_mm, roll_deg)
        return self.snapshot(bend_deg, roll_deg, feed_mm)

    def snapshot(self, bend_deg, roll_deg, feed_mm):
        triples = list(self.committed)
        forming = bend_deg if bend_deg >= BEND_MIN_DEG else 0.0
        if self.pending_straight > 0 or forming > 0:
            triples.append(self._pending_triple(forming))
        return {"feed_mm": round(feed_mm, 1), "bend_deg": round(bend_deg, 1),
                "roll_deg": round(roll_deg, 1), "n_bends": len(self.committed),
                "forming": forming > 0, "path": build_centerline(triples)}
