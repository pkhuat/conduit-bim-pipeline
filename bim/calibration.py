"""Calibration: raw geometry units -> motor steps, plus springback.

The BIM pipeline emits feeds in MILLIMETRES and bends/rolls in DEGREES. The real
machine moves in MOTOR STEPS, and conduit springs back a little after a bend so
you have to over-bend. Both conversions are per-machine. This module holds the
conversion functions and a small editable config (a JSON file) so the shop's real
numbers plug straight in from the Calibration screen — then `calibrated` flips to
True and every job also carries motor-step values. Nothing downstream changes
shape, only the numbers.

    from calibration import mm_to_steps, deg_to_steps, springback, CALIBRATED, load, save, config
"""

import json
import os

# Where the editable calibration lives (writable; set CONDUIT_CALIB_FILE to relocate).
CALIB_FILE = os.environ.get("CONDUIT_CALIB_FILE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibration.local.json")

# Defaults — the anchor from Josh's 2026-06-30 bend-calibration session for the BEND
# axis (~19,507 steps/deg for one setup); the rest are 1:1 stand-ins until measured.
DEFAULTS = {
    "calibrated": False,
    "advance_steps_per_mm": 1.0,       # ADVANCE axis (feed distance)
    "rotate_steps_per_deg": 1.0,       # ROTATE axis (roll)
    "bend_steps_per_deg": 19507.0,     # BEND axis (early anchor, not final)
    "springback_factor": 0.0,          # commanded = target*(1+factor) + offset
    "springback_offset_deg": 0.0,
}

# Live module state (updated by load()/save()); kept for the existing callers.
CALIBRATED = False
CALIBRATION = {"advance_steps_per_mm": 1.0, "rotate_steps_per_deg": 1.0, "bend_steps_per_deg": 19507.0}
SPRINGBACK = {"factor": 0.0, "offset_deg": 0.0}


def _apply(cfg):
    global CALIBRATED, CALIBRATION, SPRINGBACK
    CALIBRATED = bool(cfg.get("calibrated", False))
    CALIBRATION = {k: float(cfg.get(k, DEFAULTS[k])) for k in
                   ("advance_steps_per_mm", "rotate_steps_per_deg", "bend_steps_per_deg")}
    SPRINGBACK = {"factor": float(cfg.get("springback_factor", 0.0)),
                  "offset_deg": float(cfg.get("springback_offset_deg", 0.0))}


def config():
    """Current calibration as a flat dict (for the API / screen)."""
    return {"calibrated": CALIBRATED, **CALIBRATION,
            "springback_factor": SPRINGBACK["factor"], "springback_offset_deg": SPRINGBACK["offset_deg"]}


def load():
    """Load calibration from the config file (file is the source of truth across
    workers); falls back to DEFAULTS if absent/unreadable."""
    try:
        with open(CALIB_FILE) as fh:
            _apply({**DEFAULTS, **json.load(fh)})
    except (OSError, ValueError):
        _apply(DEFAULTS)
    return config()


def save(patch):
    """Merge a patch of fields into the current config, persist it, and return it."""
    merged = {**DEFAULTS, **config(), **{k: v for k, v in (patch or {}).items() if v is not None}}
    _apply(merged)
    try:
        with open(CALIB_FILE, "w") as fh:
            json.dump(config(), fh, indent=2)
    except OSError:
        pass
    return config()


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
    mm/deg — a NO-OP until CALIBRATED. Handles a single run ({'pieces': ...}) or all
    runs ({'runs': [...]})."""
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


load()   # initialize module state at import
