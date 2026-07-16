"""Drive the (simulated) machine from the BIM pipeline's per-stick job.json.

This is the bridge between the two halves of the project:
  - bim/process.py emits <name>_job.json — per 10-ft stick, take-up-corrected
    feed / angle / roll for every bend (derived from the Revit model).
  - programs/test_program.py's standard_bend() is the motor choreography Josh
    mapped from the manual-controller video, but for a single hardcoded bend.

Here we generalize that choreography into bend_one(feed, angle, roll) and loop it
over each stick's bends from the pipeline — so a real stick from the building runs
end to end as firmware commands. Simulation only: SimMachine opens no serial port
and nothing physical can move.

    python3 run_stick_job.py                                  # sample building, hardest run
    python3 run_stick_job.py bim/out/conduit_dtv_job.json     # a specific job.json file
    python3 run_stick_job.py --run 32                         # ANY run, extracted live
    python3 run_stick_job.py --run 1 --sticks 1,2             # just sticks 1 & 2 of run 1
    python3 run_stick_job.py --run 5 --ifc path/to/other.ifc  # a run from another IFC

Uncalibrated (bend degrees / advance units are raw, not motor steps) and not
hardware-reviewed. Chuck close/open is still Josh's open question — see _chuck().
"""

import argparse
import json
import os
import sys

from machine.sim_machine import SimMachine


def _chuck(machine, close, verbose=True):
    """Hold / release the conduit. chuck_close()/chuck_open() were removed from
    Machine when the chuck moved to a jog motor (Josh's open question), so fall
    back to a note if they're absent rather than crashing the run."""
    name = "chuck_close" if close else "chuck_open"
    if hasattr(machine, name):
        getattr(machine, name)()
    elif verbose:
        print(f"    [chuck {'close' if close else 'open'} pending — {name}() not in Machine yet]")


def signed_roll(bend):
    """Roll for the ROTATE axis: magnitude (rotate) with its direction (roll_dir)."""
    return bend.get("rotate", 0.0) * (bend.get("roll_dir", 0) or 1)


def bend_one(machine, feed, angle, roll):
    """One bend, choreographed like standard_bend() but parameterized from the
    pipeline: feed the conduit, roll to the bend plane, engage the squeeze rollers,
    bend (with a springback back-off placeholder), release the rollers, return."""
    machine.advance_enable()
    machine.advance_by(feed)                    # feed the corrected distance
    machine.advance_disable()                   # disabled so it can backdrive
    if roll:
        machine.rotate_enable()
        machine.rotate_to(roll)                 # roll to the bend plane
        machine.rotate_disable()
    machine.squeeze_enable()
    machine.squeeze_close()                     # clamp the conduit
    machine.squeeze_disable()                   # disabled so the bend motor drives it
    machine.bend_enable()
    machine.bend_to(angle)
    machine.bend_to(angle - 10)                 # back off ~10° (springback placeholder)
    machine.squeeze_enable()
    machine.squeeze_open()                      # release the rollers
    machine.bend_to(0)                          # return the bend arm


def run_stick(machine, bends, label, verbose=True):
    if verbose:
        print(f"\n=== {label}: {len(bends)} bend(s) ===")
    _chuck(machine, True, verbose)               # chuck the loaded stick once
    for j, b in enumerate(bends, 1):
        if verbose:
            print(f"  -- bend {j}: feed {b['advance']:g}, angle {b['angle']:g}°, "
                  f"roll {signed_roll(b):g}°")
        bend_one(machine, b["advance"], b["angle"], signed_roll(b))
    _chuck(machine, False, verbose)              # release


def _to_job_bends(bends):
    """Normalize a stick's bends to the machine field names, whether they came from
    a job.json (already 'advance') or straight off the pipeline ('feed')."""
    return [{"advance": b.get("advance", b.get("feed")), "rotate": b["rotate"],
             "roll_dir": b.get("roll_dir", 0), "angle": b["angle"]} for b in bends]


def sticks_from_job(job_path):
    """Bent sticks from a pre-generated <name>_job.json."""
    with open(job_path) as fh:
        job = json.load(fh)
    sticks = [(p["piece"], _to_job_bends(p["bends"]))
              for p in job.get("pieces", []) if p["bends"]]
    return job.get("name", job_path), sticks


def sticks_from_run(ifc_path, run_no, only=None):
    """Bent sticks of one run, extracted live from an IFC (so any run is runnable,
    not just the most-complex one baked into job.json)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bim"))
    import bend_report as br
    _, rows = br.run_rows(ifc_path)
    run = next((r for r in rows if r["run"] == run_no), None)
    if run is None:
        nums = sorted(r["run"] for r in rows)
        raise SystemExit(f"run {run_no} not found in {os.path.basename(ifc_path)} "
                         f"(runs {nums[0]}..{nums[-1]})")
    sticks = [(i, _to_job_bends(p["bends"]))
              for i, p in enumerate(run["pieces"], 1)
              if p["bends"] and (only is None or i in only)]
    return f"{os.path.basename(ifc_path)} — run {run_no}", sticks


def all_runs_sticks(ifc_path):
    """Every bent run's bent sticks — for driving a whole building. Returns
    (name, [(run_no, [(piece_no, bends), ...]), ...])."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bim"))
    import bend_report as br
    _, rows = br.run_rows(ifc_path)
    runs = []
    for r in rows:
        bent = [(i, _to_job_bends(p["bends"]))
                for i, p in enumerate(r["pieces"], 1) if p["bends"]]
        if bent:
            runs.append((r["run"], bent))
    return f"{os.path.basename(ifc_path)} (whole building)", runs


def main():
    ap = argparse.ArgumentParser(
        description="Drive the simulated machine from the BIM pipeline.")
    ap.add_argument("job", nargs="?",
                    help="a bim/out/<name>_job.json (default: the sample building)")
    ap.add_argument("--run", type=int,
                    help="drive this run number, extracted live from --ifc")
    ap.add_argument("--all", action="store_true",
                    help="drive EVERY bent run in --ifc (whole building; compact summary)")
    ap.add_argument("--ifc", default="bim/samples/sample_elec.ifc",
                    help="IFC to extract when using --run/--all (default: the sample building)")
    ap.add_argument("--sticks",
                    help="with --run, limit to these stick numbers, e.g. 1,2")
    args = ap.parse_args()

    if args.all:                                 # whole-building drive, compact
        name, runs = all_runs_sticks(args.ifc)
        n_sticks = sum(len(s) for _, s in runs)
        print("=" * 60)
        print("  DRIVE WHOLE BUILDING THROUGH THE MACHINE  (SIMULATION)")
        print(f"  {name}   —   {len(runs)} bent run(s), {n_sticks} bent stick(s)")
        print("=" * 60)
        machine = SimMachine(verbose=False)
        for run_no, sticks in runs:
            for piece_no, bends in sticks:
                run_stick(machine, bends, f"run {run_no} stick {piece_no}", verbose=False)
        print(f"  Done: {len(machine.history)} firmware commands, "
              f"{len(machine.warnings)} warning(s) across {len(runs)} runs.")
        return

    if args.run is not None:
        only = {int(s) for s in args.sticks.split(",")} if args.sticks else None
        name, sticks = sticks_from_run(args.ifc, args.run, only)
    else:
        name, sticks = sticks_from_job(args.job or "bim/out/sample_elec_job.json")

    print("=" * 60)
    print("  DRIVE MACHINE FROM PIPELINE  (SIMULATION)")
    print(f"  {name}   —   {len(sticks)} bent stick(s) to run")
    print("=" * 60)

    machine = SimMachine()
    for piece_no, bends in sticks:
        run_stick(machine, bends, f"STICK {piece_no}")

    print()
    print(machine.summary())
    print(f"\nCommands sent: {len(machine.history)}   "
          f"Warnings: {len(machine.warnings)}")


if __name__ == "__main__":
    main()
