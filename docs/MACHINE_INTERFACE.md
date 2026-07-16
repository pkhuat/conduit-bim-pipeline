# Machine Interface — the handoff contract

This is the seam between the **software** (this repo: BIM → fabrication recipe) and
the **machine** (the Pi + ClearCore firmware that drives the motors). Two things
cross the seam:

1. **`job.json`** — the machine-readable bend job (data: *what* to bend).
2. **the command protocol** (`machine/commands.py`) — the ClearCore vocabulary
   (*how* it's driven).

The machine side reads a `job.json` and issues the commands below. Everything up to
`job.json` is produced by `bim/process.py`; everything after it is the machine.

---

## 1. `job.json` — the bend job

Written by `bim/process.py` as `bim/out/<name>_job.json` (the most-complex run) and
`bim/out/<name>_all_jobs.json` (every bent run). One run = an ordered list of
**pieces** (10-ft sticks); one piece = an ordered list of **bends**.

```jsonc
{
  "name": "sample_elec — most complex conduit run (run 20)",
  "units": "millimetres of conduit feed / degrees of turn - NOT motor steps",
  "calibrated": false,          // true once motor-step/springback values are set (see §3)
  "conduit": "EMT",
  "die": "EMT 2\"",             // the Greenlee 555 shoe to load (conduit type + trade size)
  "outer_diameter_mm": 55.8,
  "bend_radius_mm": 241.3,      // shoe centerline radius used for take-up
  "stick_length_ft": 10.0,
  "pieces": [
    {
      "piece": 1,
      "load": "open end",       // "open end" | "coupler" — leading end of the stick
      "end":  "coupler",        // "open end" | "coupler" — trailing end
      "length_ft": 9.42,        // route span of the stick
      "cut_length_ft": 9.08,    // developed length to cut (straights + bend arcs)
      "bends": [
        {
          "advance":  1130.3,   // FEED before this bend, mm, take-up corrected (ADVANCE axis)
          "angle":    90.0,     // bend angle, degrees (BEND axis)
          "rotate":   0.0,      // roll magnitude vs previous bend, 0..180 degrees (ROTATE axis)
          "roll_dir": 0         // roll direction: +1 / -1 / 0  (see §3 — confirm CW/CCW)
        }
      ],
      "tail_advance": 977.9     // straight remaining after the last bend, mm
    }
  ]
}
```

`<name>_all_jobs.json` wraps every bent run:
```jsonc
{ "name": "...", "units": "...", "runs": [ { "run": 1, "conduit": "EMT", "die": "EMT 2\"",
  "pieces": [ ... same piece shape ... ] }, ... ] }
```

**Contract guarantees**
- Feeds are in **mm of conduit**, angles/rolls in **degrees** — NOT motor steps (see §3).
- Feeds are **take-up corrected** for `bend_radius_mm` (the mark, not the centerline corner).
- Pieces are ≤ `stick_length_ft`; couplers only ever fall on straight sections.
- `bends` is in fabrication order; drive them in sequence.

## 2. Driving a job — the command protocol

`machine/commands.py` defines the ClearCore command grammar. To execute a piece,
issue (this is exactly what `run_stick_job.bend_one()` does per bend):

```
ADVANCE ENABLE ; ADVANCE BY <advance> ; ADVANCE DISABLE      # feed to the mark
ROTATE  ENABLE ; ROTATE  TO <signed roll> ; ROTATE DISABLE   # roll to the bend plane (skip if 0)
SQUEEZE ENABLE ; SQUEEZE CLOSE ; SQUEEZE DISABLE             # clamp
BEND    ENABLE ; BEND TO <angle> ; BEND TO <angle-backoff>   # bend, then relieve springback
SQUEEZE ENABLE ; SQUEEZE OPEN                                # release
BEND    TO 0                                                 # return the bend arm
```

Full vocabulary (each `*_enable/disable/to/by/jog/home`, plus `SQUEEZE OPEN/CLOSE`,
`CHUCK ENABLE/DISABLE/JOG`, `STATUS <axis>`, `ZERO <axis>`, `PING`, `ESTOP`) is in
`machine/commands.py`. `SimMachine` implements it as a firmware model; the real
machine implements the same interface over serial.

**Open on the machine side:** the chuck. `commands.py` has `chuck_enable/disable/jog`
(board 2). If the chuck engages via a discrete close/open instead of jogging, add
`chuck_close`/`chuck_open` to the interface — the driver already probes for them.

## 3. Units, calibration & springback (§ the one config to flip)

The job is in **mm and degrees** because motor steps and springback are per-machine
and measured on hardware. `bim/calibration.py` holds the conversion:

- `CALIBRATION`: `advance_steps_per_mm`, `rotate_steps_per_deg`, `bend_steps_per_deg`
  (seeded with the ~19,507 steps/° bend anchor from 2026-06-30).
- `SPRINGBACK`: `factor`, `offset_deg` — over-bend so the conduit relaxes to target.
- `CALIBRATED = False` until the shop's real values are measured.

When the numbers are in: set them in `calibration.py`, flip `CALIBRATED = True`, and
`job.json` carries `"calibrated": true` (and, via `calibration.apply_to_job`, per-bend
step values alongside the mm/deg).

**Roll direction (`roll_dir`)** is geometrically consistent (right-hand rule about the
feed axis) but the **CW-vs-CCW mapping is unconfirmed against the machine's ROTATE+
direction**. If it's reversed on hardware, flip the sign in `extract_conduit.derive_bends`
— a one-line change.
