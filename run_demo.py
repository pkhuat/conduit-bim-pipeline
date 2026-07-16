"""Safe demo: run a bend job against the Tubender simulator.

Usage:
    python3 run_demo.py [path/to/job.json]

Defaults to programs/example_job.json. This never opens a serial port and
cannot move the machine: every command is executed against SimMachine, the
software model of the firmware (see README, "Simulation mode"). It is meant to
be run live in front of the team, so the output is framed for a screen.
"""

import json
import sys

from machine.sim_machine import SimMachine
from programs.bend_job import load_job, run_job

DEFAULT_JOB = "programs/example_job.json"
EXAMPLE_JOBS = (
    "programs/example_job.json",
    "programs/offset_bend.json",
    "programs/saddle_bend.json",
)
# Order matches SimMachine.summary(); CHUCK/SQUEEZE stay at 0 for bend jobs but
# are shown so the table is the whole machine, not just the moving axes.
AXES = ("ADVANCE", "ROTATE", "BEND", "SQUEEZE", "CHUCK")
WIDTH = 66


def rule(char="-"):
    print(char * WIDTH)


def banner(title):
    rule("=")
    print(title)
    rule("=")


def read_meta(path):
    """Read the optional name/description/units fields for display.

    Kept separate from bend_job.load_job so that module stays a plain data
    loader; the demo is the only thing that cares about presentation text.
    """
    with open(path) as f:
        data = json.load(f)
    return {
        "name": data.get("name", path),
        "description": data.get("description", ""),
        "units": data.get("units", ""),
    }


def print_job_table(bends):
    print(f"  {'#':>2}  {'ADVANCE':>9}  {'ROTATE':>8}  {'BEND':>8}")
    print(f"  {'':->2}  {'':->9}  {'':->8}  {'':->8}")
    for i, b in enumerate(bends, 1):
        print(f"  {i:>2}  {b.advance:>9g}  {b.rotate:>8g}  {b.angle:>8g}")


def snapshot(machine):
    return {name: dict(machine.axes[name]) for name in machine.axes}


def print_state_table(before, after):
    print(f"  {'AXIS':<8}  {'BEFORE':>8}  {'AFTER':>8}  {'ENABLED':>8}")
    print(f"  {'':-<8}  {'':->8}  {'':->8}  {'':->8}")
    for name in AXES:
        print(
            f"  {name:<8}  {before[name]['position']:>8g}  "
            f"{after[name]['position']:>8g}  {str(after[name]['enabled']):>8}"
        )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JOB
    meta = read_meta(path)
    bends = load_job(path)

    banner("TUBENDER V2  -  BEND JOB DEMO  (SIMULATION)")
    print("No serial ports are opened and no motor can move. Every command below")
    print("is a real firmware instruction, executed against the software model of")
    print("the machine instead of the hardware.")
    print()
    print(f"  Job:   {meta['name']}")
    if meta["description"]:
        print(f"  About: {meta['description']}")
    if meta["units"]:
        print(f"  Units: {meta['units']}")
    print(f"  File:  {path}")
    print()
    print(f"This job has {len(bends)} bend(s):")
    print_job_table(bends)
    print()

    machine = SimMachine()
    before = snapshot(machine)

    print()
    banner("EXECUTING  -  command stream to the (simulated) firmware")
    run_job(machine, bends)
    after = snapshot(machine)

    print()
    banner("RESULT")
    print_state_table(before, after)
    print()
    print(f"  Commands sent: {len(machine.history)}")
    if machine.warnings:
        print(f"  Warnings:      {len(machine.warnings)}")
        for w in machine.warnings:
            print(f"    - {w}")
    else:
        print("  Warnings:      none")
    print()

    rule()
    print("Worth saying out loud during the demo:")
    print("  * Simulation only - this proves the control software and command")
    print("    pipeline end to end, not the physical machine.")
    print("  * Values are raw motor units. Degrees/mm calibration is still TODO,")
    print("    so 'bend 90' does not yet mean 90 degrees on hardware.")
    print("  * The run_job bend sequence is a first pass, not yet hardware-reviewed.")
    print()
    others = [j for j in EXAMPLE_JOBS if j != path]
    if others:
        print("Other jobs to show:")
        for j in others:
            print(f"  python3 run_demo.py {j}")


if __name__ == "__main__":
    main()
