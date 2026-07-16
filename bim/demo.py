"""Live demo: read a real Revit building IFC and show, in readable form, what the
extractor pulls out — without dumping all 530 segments.

    python3 bim/demo.py                         # the sample building
    python3 bim/demo.py bim/samples/conduit_dtv.ifc

Tells the whole story in one screen: how many conduit pieces, how they group into
runs via the IFC ports, that the derived bend angles land on the standard
electrician angles, and the single most complex run (written out as a runnable
bend job).
"""

import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ifcopenshell
import ifcopenshell.util.unit
import extract_conduit as ec

DEFAULT = os.path.join(os.path.dirname(__file__), "samples", "sample_elec.ifc")
OUT = os.path.join(os.path.dirname(__file__), "derived_job_complex.json")


def clean_bends(run):
    poly = ec.drop_near_straight(ec.simplify_polyline(run, ec.SIMPLIFY_TOL), ec.MIN_BEND_DEG)
    bends, _, _ = ec.derive_bends(poly)
    for b in bends:
        b["angle"] = round(ec.snap_to_trade(b["angle"]), 1)
        b["rotate"] = round(ec.snap_roll(b["rotate"]), 1)
    return bends


def bar(n, scale=1):
    return "#" * max(1, round(n / scale))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    ec.rule("=")
    print("TUBENDER  —  BIM  ->  BEND JOB   (live demo)")
    ec.rule("=")

    model = ifcopenshell.open(path)
    scale = ifcopenshell.util.unit.calculate_unit_scale(model) * 1000.0
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")

    ods = [round(ec.outer_diameter(s) * scale, 1) for s in segs if ec.outer_diameter(s)]
    kinds = [ec.conduit_kind(s) for s in segs if ec.conduit_kind(s)]
    od = max(set(ods), key=ods.count) if ods else "?"
    kind = max(set(kinds), key=kinds.count) if kinds else "?"
    ports = len(model.by_type("IfcRelConnectsPorts"))

    print(f"  Reading : {os.path.basename(path)}   (real Revit export, schema {model.schema})")
    print(f"  Conduit : {len(segs)} segments + {len(fits)} fittings  —  {kind}, OD {od} mm")
    print(f"  Wiring  : {ports} IFC connection-port links join the pieces into runs")
    print()

    t0 = time.time()
    runs = ec.port_based_runs(model, segs, fits, scale=scale)
    elapsed = time.time() - t0

    per_run = [clean_bends(r) for r in runs]
    total = sum(len(b) for b in per_run)
    bent = sum(1 for b in per_run if b)
    print(f"  Grouped into {len(runs)} runs ({bent} with bends) and derived "
          f"{total} bends in {elapsed:.1f}s.")
    print()

    hist = Counter(b["angle"] for bends in per_run for b in bends)
    print("  Derived bend angles land on the STANDARD electrician angles:")
    biggest = max(hist.values()) if hist else 1
    for ang in sorted(hist):
        tag = "" if ang in ec.TRADE_ANGLES else "   <- non-standard (left flagged)"
        print(f"     {ang:5}° | {bar(hist[ang], biggest/40):40s} {hist[ang]}{tag}")
    print()

    # most complex run -> write a runnable job
    gi = max(range(len(runs)), key=lambda i: len(per_run[i]))
    bends = per_run[gi]
    job = {
        "name": f"{os.path.basename(path)} — most complex conduit run",
        "description": "Auto-derived from a real Revit export via IFC + port-based "
                       "grouping + trade-angle/roll cleanup. Uncalibrated.",
        "units": "millimetres of centerline / degrees of turn - NOT motor steps",
        "conduit": kind,
        "outer_diameter_mm": od,
        "bends": bends,
    }
    json.dump(job, open(OUT, "w"), indent=2)
    print(f"  Most complex run: {ec.path_length(runs[gi]) / 1000:.1f} m, {len(bends)} bends")
    print(f"     angles: {[b['angle'] for b in bends]}")
    print(f"     -> wrote {os.path.relpath(OUT)}")
    print(f"     -> run it through the machine sim:  python3 run_demo.py {os.path.relpath(OUT)}")
    print()


if __name__ == "__main__":
    main()
