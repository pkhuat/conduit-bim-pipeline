"""Calibration scaffold: raw geometry units -> motor steps, plus springback.

The BIM pipeline emits feeds in MILLIMETRES and bends/rolls in DEGREES. The real
machine moves in MOTOR STEPS, and conduit springs back a little after a bend so
you have to over-bend. Both conversions are per-machine and NOT yet fully measured
on hardware — this module holds the placeholders and the conversion functions so
the shop's real numbers plug straight in: edit CALIBRATION / SPRINGBACK and flip
CALIBRATED = True. Nothing downstream changes shape, only the numbers.

    from calibration import mm_to_steps, deg_to_steps, springback, CALIBRATED
"""

# Flip to True once every value below is measured on the machine and reviewed.
CALIBRATED = False

# steps-per-unit for each axis. ASSUMPTION / PLACEHOLDER — confirm on the machine.
# bend_steps_per_deg seeds from Josh's 2026-06-30 anchor (~19,507 steps/deg for
# one setup, from the squeeze-ballscrew/bend-calibration session); the rest are 1:1
# stand-ins until measured.
CALIBRATION = {
    "advance_steps_per_mm": 1.0,       # ADVANCE axis (feed distance)
    "rotate_steps_per_deg": 1.0,       # ROTATE axis (roll)
    "bend_steps_per_deg":   19507.0,   # BEND axis (early anchor, not final)
}

# Springback: commanded = target * (1 + factor) + offset_deg. Zeros = identity
# (no compensation) until real springback is characterized per conduit/size.
SPRINGBACK = {"factor": 0.0, "offset_deg": 0.0}


def mm_to_steps(mm):
    """Advance distance (mm) -> ADVANCE motor steps."""
    return mm * CALIBRATION["advance_steps_per_mm"]


def deg_to_steps(deg, axis="bend"):
    """Angle (deg) -> motor steps for `axis` ('bend' or 'rotate')."""
    return deg * CALIBRATION[f"{axis}_steps_per_deg"]


def springback(target_deg):
    """Target bend angle -> the (over-)bend angle to actually command."""
    return target_deg * (1.0 + SPRINGBACK["factor"]) + SPRINGBACK["offset_deg"]


def apply_to_job(job):
    """Annotate a job dict's bends with motor-step / over-bend values alongside the
    mm/deg — a NO-OP until CALIBRATED (so the plumbing ships now, numbers drop in
    later). Handles a single run ({'pieces': ...}) or all runs ({'runs': [...]})."""
    if not CALIBRATED:
        return job
    for run in job.get("runs", [job]):
        for piece in run.get("pieces", []):
            for b in piece.get("bends", []):
                signed_roll = b.get("rotate", 0.0) * (b.get("roll_dir", 0) or 1)
                b["advance_steps"] = round(mm_to_steps(b.get("advance", 0.0)))
                b["bend_steps"] = round(deg_to_steps(springback(b.get("angle", 0.0)), "bend"))
                b["rotate_steps"] = round(deg_to_steps(signed_roll, "rotate"))
    job["calibrated"] = True
    return job
