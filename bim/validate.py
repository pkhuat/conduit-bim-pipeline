"""Round-trip validation: does the bend recipe actually rebuild the model?

For each run we take the (advance, angle, roll) recipe we derived — the exact
numbers a fabricator or the machine would bend from — and walk it back into a 3D
polyline. Then we compare that reconstruction to the run's real centerline from
the IFC and report the largest deviation. Small deviation = the recipe faithfully
reproduces the design; the deviation is essentially what the "snap to trade
angles" cleanup moved.

    python3 bim/validate.py                         # the sample building
    python3 bim/validate.py bim/samples/conduit_dtv.ifc

The reconstruction is seeded with the run's true start point, initial direction,
and first bend plane (the recipe's rolls are all *relative*, exactly like loading
the first stick into the bender), then it uses only the recipe from there.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ifcopenshell
import ifcopenshell.util.unit
import extract_conduit as ec

DEFAULT = os.path.join(os.path.dirname(__file__), "samples", "sample_elec.ifc")
MM_PER_FT = 304.8


def _rot(v, axis, deg):
    """Rodrigues rotation: rotate vector v about `axis` by `deg` degrees."""
    a = np.radians(deg)
    k = np.asarray(axis, float)
    k = k / (np.linalg.norm(k) or 1.0)
    v = np.asarray(v, float)
    return v * np.cos(a) + np.cross(k, v) * np.sin(a) + k * np.dot(k, v) * (1 - np.cos(a))


def reconstruct(clean_verts):
    """Rebuild a run's polyline from its bend recipe, seeded with the run's true
    start / initial direction / first bend plane. Returns a vertex list the same
    length as clean_verts (start + one per bend + end)."""
    bends, _, tail = ec.derive_bends(clean_verts)
    for b in bends:                                   # clean to trade standards, as the pipeline does
        b["angle"] = round(ec.snap_to_trade(b["angle"]), 1)
        b["rotate"] = round(ec.snap_roll(b["rotate"]), 1)

    p = np.asarray(clean_verts[0], float)
    d = np.asarray(ec.sub(clean_verts[1], clean_verts[0]), float)
    d = d / (np.linalg.norm(d) or 1.0)
    n = np.cross(ec.sub(clean_verts[1], clean_verts[0]),
                 ec.sub(clean_verts[2], clean_verts[1]))
    n = n / (np.linalg.norm(n) or 1.0)                # first bend plane (seed)

    out = [p.copy()]
    for k, b in enumerate(bends):
        p = p + d * b["advance"]                      # straight feed
        out.append(p.copy())
        if k > 0:                                     # roll the bend plane about the conduit axis
            n = _rot(n, d, b["rotate"] * (b.get("roll_dir", 0) or 1))
        d = _rot(d, n, b["angle"])                    # turn within the plane
        d = d / (np.linalg.norm(d) or 1.0)
    p = p + d * tail
    out.append(p.copy())
    return out


def run_deviations(path):
    """Return (info, [per-run dicts]) with the max reconstruction deviation."""
    model = ifcopenshell.open(path)
    scale = ifcopenshell.util.unit.calculate_unit_scale(model) * 1000.0
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    runs = ec.port_based_runs(model, segs, fits, scale=scale)

    rows = []
    for i, poly in enumerate(runs, 1):
        clean = ec.drop_near_straight(ec.simplify_polyline(poly, ec.SIMPLIFY_TOL), ec.MIN_BEND_DEG)
        if len(clean) < 3:
            continue                                  # straight run — nothing to reconstruct
        rebuilt = reconstruct(clean)
        devs = [float(np.linalg.norm(np.asarray(a, float) - b)) for a, b in zip(clean, rebuilt)]
        # which bend's trade-angle snap moved the most (the usual cause of drift)
        bends, _, _ = ec.derive_bends(clean)
        snap = max(((b["angle"], round(ec.snap_to_trade(b["angle"]), 1)) for b in bends),
                   key=lambda t: abs(t[1] - t[0]), default=(0.0, 0.0))
        rows.append({"run": i, "n_bends": len(clean) - 2,
                     "length_mm": ec.path_length(clean), "max_dev_mm": max(devs),
                     "raw_deg": snap[0], "snapped_deg": snap[1],
                     "snap_delta": abs(snap[1] - snap[0])})
    info = {"file": os.path.basename(path), "n_runs": len(rows)}
    return info, rows


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    info, rows = run_deviations(path)
    if not rows:
        print("No bent runs to validate.")
        return
    rows.sort(key=lambda r: r["max_dev_mm"], reverse=True)
    worst = rows[0]["max_dev_mm"]
    median = sorted(r["max_dev_mm"] for r in rows)[len(rows) // 2]

    ec.rule("=")
    print("  ROUND-TRIP VALIDATION — recipe rebuilt vs. the model")
    print(f"  source: {info['file']}   ({len(rows)} bent runs)")
    ec.rule("=")
    print(f"  worst run deviation: {worst:.1f} mm ({worst / 25.4:.2f} in)")
    print(f"  median deviation:    {median:.1f} mm ({median / 25.4:.2f} in)")
    print()
    print(f"   {'Run':>4}  {'Bends':>5}  {'Length':>9}  {'Max dev':>9}   Worst angle snap")
    print(f"   {'-'*4}  {'-'*5}  {'-'*9}  {'-'*9}   {'-'*18}")
    for r in rows[:10]:
        snap = (f"{r['raw_deg']:g}° -> {r['snapped_deg']:g}° ({r['snap_delta']:.1f}°)"
                if r["snap_delta"] > 0.05 else "—")
        print(f"   {r['run']:>4}  {r['n_bends']:>5}  {r['length_mm']/MM_PER_FT:>7.1f}ft  "
              f"{r['max_dev_mm']:>7.1f}mm   {snap}")
    print(f"\n  Deviation is the trade-angle snap propagated along the run — a small-angle")
    print(f"  bend snapped near the 4° tolerance on a long run swings the far end the most.")


if __name__ == "__main__":
    main()
