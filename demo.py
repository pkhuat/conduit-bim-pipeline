"""One command: the whole arc — BIM model to machine, end to end (simulation).

    python3 demo.py                              # the sample building
    python3 demo.py bim/samples/conduit_dtv.ifc  # the small hand-built check
    python3 demo.py --run 32                      # feature a specific run at the machine

Stage 1 runs the full pipeline on the IFC (extract -> per-stick recipe, CSVs,
bend cards, diagrams, BOM, data-health, machine job). Stage 2 takes one run's
hardest stick and drives it through the simulated machine, so you watch Revit
geometry become take-up-corrected feeds become firmware commands — same numbers
the whole way. Nothing physical moves.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "bim"))

import process                       # noqa: E402  (the pipeline)
import bend_report as br             # noqa: E402
from machine.sim_machine import SimMachine   # noqa: E402
import run_stick_job as rsj          # noqa: E402


def rule(c="="):
    print(c * 66)


def main():
    ap = argparse.ArgumentParser(description="BIM -> machine, end to end (sim).")
    ap.add_argument("ifc", nargs="?", default="bim/samples/sample_elec.ifc")
    ap.add_argument("--run", type=int, help="which run to feature through the machine")
    args = ap.parse_args()

    rule()
    print("  TUBENDER — BIM MODEL TO MACHINE, END TO END  (SIMULATION)")
    rule()
    print(f"  input:  {args.ifc}")
    print("  No serial ports open; nothing physical can move.\n")

    # ── STAGE 1 — extract & organize (prints the schedule, BOM, and data-health) ──
    print(">>> STAGE 1 — extract the model into fabrication data\n")
    process.process_one(args.ifc)

    # ── STAGE 2 — drive one run's hardest stick through the machine ──
    stem = os.path.splitext(os.path.basename(args.ifc))[0]
    if args.run is not None:
        name, sticks = rsj.sticks_from_run(args.ifc, args.run)
    else:
        name, sticks = rsj.sticks_from_job(os.path.join(HERE, "bim", "out", f"{stem}_job.json"))
    if not sticks:
        print("  (no bent sticks to drive)")
        return
    piece_no, bends = max(sticks, key=lambda s: len(s[1]))   # the most interesting stick

    print()
    rule()
    print(f">>> STAGE 2 — bend one stick on the machine   ({name}, its hardest stick)")
    rule()
    machine = SimMachine()
    rsj.run_stick(machine, bends, f"STICK {piece_no}")
    print()
    print(machine.summary())

    # ── closing ──
    print()
    rule()
    print("  THE WHOLE ARC WORKED:")
    print(f"    Revit model  →  organized recipe (see bim/out/{stem}_cards.html)")
    print(f"    recipe       →  machine job (bim/out/{stem}_job.json)")
    print(f"    job          →  {len(machine.history)} firmware commands, "
          f"{len(machine.warnings)} warnings, in the simulator")
    print("  Same feed/angle/roll numbers from the model all the way to the machine.")
    rule()


if __name__ == "__main__":
    main()
