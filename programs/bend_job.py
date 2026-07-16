"""Bend job format — the target output of the future BIM pipeline.

A job is an ordered list of bends. Each bend is the (advance, rotate, angle)
triple that the machine vocabulary already speaks:

    advance — feed distance before this bend (ADVANCE axis)
    rotate  — rotation relative to the previous bend plane, degrees (ROTATE axis)
    angle   — bend angle, degrees (BEND axis)

Units are currently uncalibrated: the firmware treats all values as raw motor
steps until the degrees/mm conversions are implemented (see README,
"Calibration status"). The format itself doesn't change when calibration
lands — only the meaning of the numbers does.

Sequencing in run_job is a first pass for simulation only. The real-machine
sequence (squeeze/chuck handling, springback compensation, bend-arm return)
needs to be designed with the team before this ever drives hardware — which
is why run_job refuses a real Machine by default.
"""

import json
from dataclasses import dataclass


@dataclass
class Bend:
    advance: float
    rotate: float
    angle: float


def load_job(path):
    """Load a bend job from a JSON file into an ordered list of Bends.

    Accepts two shapes:
      - flat:  {"bends": [{advance, rotate, angle}, ...]}   (see example_job.json)
      - sticks:{"pieces": [{"bends": [...], ...}, ...]}      (the BIM pipeline's
        per-10-ft-stick output; its bend feeds are take-up corrected). The sticks
        are concatenated in order — each stick is loaded, advanced, and bent — so
        the simulator runs the whole run as one command stream.
    """
    with open(path) as f:
        data = json.load(f)
    bends = data.get("bends")
    if bends is None and "pieces" in data:
        bends = [b for p in data["pieces"] for b in p.get("bends", [])]
    return [
        Bend(b["advance"], b.get("rotate", 0.0), b["angle"])
        for b in (bends or [])
    ]


def run_job(machine, bends, allow_real=False):
    """Execute a bend job. Refuses a real Machine unless allow_real=True.

    The override exists for the future calibrated machine, not for today:
    only pass allow_real=True after team review, with calibration done and
    someone standing at the physical e-stop.
    """
    from machine.sim_machine import SimMachine
    if not isinstance(machine, SimMachine) and not allow_real:
        raise RuntimeError(
            "run_job refused to drive a real Machine. This sequencing is "
            "untested on hardware. Pass allow_real=True only after team "
            "review, calibration, and with someone at the physical e-stop."
        )

    machine.advance_enable()
    machine.rotate_enable()
    machine.bend_enable()
    machine.zero("ADVANCE")
    machine.zero("ROTATE")
    machine.zero("BEND")

    for i, b in enumerate(bends, 1):
        print(f"--- bend {i}/{len(bends)}: advance {b.advance}, rotate {b.rotate}, bend {b.angle} ---")
        machine.advance_by(b.advance)
        if b.rotate:
            machine.rotate_by(b.rotate)
        machine.bend_to(b.angle)
        machine.bend_to(0)  # return the bend arm to release the conduit

    machine.advance_disable()
    machine.rotate_disable()
    machine.bend_disable()
