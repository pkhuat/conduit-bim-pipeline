"""Organized conduit BEND SCHEDULE from a BIM/IFC export — the readable, per-run
view of the bend data (the kind of fabrication output Allied BIM produces).

    python3 bim/bend_report.py                          # the sample building
    python3 bim/bend_report.py bim/samples/conduit_dtv.ifc

For every conduit run it answers, clearly: what conduit it is, how long it is
(it's usually longer than one 10-ft stick), how many bends it has, and -- in
order, the way it's actually fabricated -- how far you feed before each bend, the
bend angle, and which way it rolls. Also writes two spreadsheets you can open in
Excel:
    bim/conduit_runs.csv   -- one row per conduit run (size, length, # bends)
    bim/conduit_bends.csv  -- one row per bend (feed length, angle, roll)
"""

import csv
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ifcopenshell
import ifcopenshell.util.unit
import extract_conduit as ec

DEFAULT = os.path.join(os.path.dirname(__file__), "samples", "sample_elec.ifc")
HERE = os.path.dirname(__file__)
MM_PER_FT = 304.8


def short_kind(name):
    """'Electrical Metallic Tubing (EMT)' -> 'EMT'; else a short, sane label.
    Real Revit conduit names carry the trade abbreviation in parentheses; without
    one, fall back to a trimmed Latin label — or generic 'conduit' — so a raw or
    non-Latin element name never leaks through as the conduit 'kind'."""
    if not name:
        return "?"
    m = re.search(r"\(([^)]+)\)", name)
    if m:
        return m.group(1)
    if not re.search(r"[A-Za-z]", name):     # no Latin letters (e.g. Cyrillic) -> generic
        return "conduit"
    return name[:24].strip()


def run_rows(path, resolve_odd=False, resolve_runs=None):
    """Return (header_info, [per-run dicts]) for an IFC file. With resolve_odd=True,
    every bend is snapped to the nearest trade angle (standardize the odd ones).
    resolve_runs (a set of run numbers) force-snaps only those runs — so a single
    flagged run can be standardized on its own from the app."""
    resolve_runs = resolve_runs or set()
    model = ifcopenshell.open(path)
    scale = ifcopenshell.util.unit.calculate_unit_scale(model) * 1000.0
    segs, fits, n_trays = ec.conduit_elements(model)
    runs = ec.reconstruct_runs(model, segs, fits, scale=scale)

    rows = []
    for i, (poly, run_segs) in enumerate(runs, 1):
        clean = ec.drop_near_straight(ec.simplify_polyline(poly, ec.SIMPLIFY_TOL), ec.MIN_BEND_DEG)
        bends, lengths, tail = ec.derive_bends(clean)
        force = resolve_odd or (i in resolve_runs)
        for b in bends:
            b["angle"] = round(ec.snap_to_trade(b["angle"], force=force), 1)
            b["rotate"] = round(ec.snap_roll(b["rotate"]), 1)
        seg = run_segs[0] if run_segs else None
        od = ec.outer_diameter(seg) if seg else None
        od_mm = round(od * scale, 1) if od else None
        pieces, warns = ec.split_into_pieces(bends, tail,
                                             radius_mm=ec.bend_radius_mm(od_mm))
        rows.append({
            "run": i,
            "kind": short_kind(ec.conduit_kind(seg)) if seg else "?",
            "od_mm": od_mm,
            "length_mm": round(ec.path_length(clean), 1),
            "bends": bends,
            "tail_mm": round(tail, 1),
            "pieces": pieces,
            "piece_warnings": warns,
        })
    info = {
        "file": os.path.basename(path),
        "schema": model.schema,
        "n_segments": len(segs),
        "n_trays": n_trays,
        "n_runs": len(rows),
        "n_bent": sum(1 for r in rows if r["bends"]),
        "n_bends": sum(len(r["bends"]) for r in rows),
    }
    return info, rows


def fmt_ft(mm):
    return f"{mm / MM_PER_FT:.1f} ft"


def fmt_ftin(mm, denom=16):
    """Length in mm as trade feet-and-inches, marks rounded to 1/denom inch — the
    way it's marked on the conduit, not decimal feet:
        88.4 -> '3-1/2 in'   1587.5 -> '5 ft 2-1/2 in'   3048 -> '10 ft'
    """
    units = round(abs(mm) / 25.4 * denom)          # total 1/denom-inches
    feet, rem = divmod(units, 12 * denom)
    whole_in, frac = divmod(rem, denom)
    inch = str(whole_in) if whole_in else ""
    if frac:
        f = Fraction(frac, denom)
        inch = (f"{inch}-{f.numerator}/{f.denominator}" if inch
                else f"{f.numerator}/{f.denominator}")
    out = []
    if feet:
        out.append(f"{feet} ft")
    if inch:
        out.append(f"{inch} in")
    return " ".join(out) or "0 in"


def roll_dir_word(rotate, roll_dir):
    """'CW' / 'CCW' / '' — the handed direction of a roll. Blank for no roll (0)
    or a 180° flip (which has no handedness). See derive_bends for the convention
    (right-hand rule about feed; confirm CW/CCW against the machine)."""
    if not rotate or abs(rotate - 180.0) < 0.5:
        return ""
    return {1: "CW", -1: "CCW"}.get(roll_dir, "")


def roll_label(rotate, roll_dir):
    """e.g. 'roll 90 CW', 'roll 180', 'roll 0'."""
    w = roll_dir_word(rotate, roll_dir)
    return f"roll {rotate:g}" + (f" {w}" if w else "")


def fmt_op(o):
    """A trade operation (from ec.classify_ops) as readable text."""
    if o["type"] == "offset":
        return (f"{o['angle']:g}° offset — {fmt_ftin(o['rise_mm'])} rise, "
                f"{fmt_ftin(o.get('shrink_mm', 0))} shrink (×{o.get('multiplier', 0):g})")
    if o["type"] == "saddle":
        return (f"{o['angle']:g}° saddle — center {o.get('center_angle', 2 * o['angle']):g}°, "
                f"{fmt_ftin(o.get('rise_mm', 0))} rise (×{o.get('multiplier', 0):g})")
    return f"{o['angle']:g}° bend"


def job_totals(rows):
    """Aggregate the bill of materials per conduit (kind + trade size): how many
    10-ft sticks to buy, couplers, bends, and conduit used (sum of cut lengths).
    Returns (by_conduit dict keyed by label, grand-total dict)."""
    by, lens = {}, {}
    for r in rows:
        pieces = r.get("pieces") or []
        if not pieces:
            continue
        size = ec.trade_size_for_od(r["od_mm"])
        label = f'{r["kind"]} {size}"' if size else r["kind"]
        d = by.setdefault(label, {"runs": 0, "sticks": 0, "couplers": 0, "bends": 0,
                                  "offsets": 0, "saddles": 0, "len_mm": 0.0, "opt_sticks": 0})
        d["runs"] += 1
        d["sticks"] += len(pieces)
        d["couplers"] += max(len(pieces) - 1, 0)        # one fewer coupler than sticks
        d["bends"] += len(r["bends"])
        ops = ec.classify_ops(r["bends"])
        d["offsets"] += sum(1 for o in ops if o["type"] == "offset")
        d["saddles"] += sum(1 for o in ops if o["type"] == "saddle")
        cuts = [p.get("developed_mm", p.get("length_mm", 0.0)) for p in pieces]
        d["len_mm"] += sum(cuts)
        lens.setdefault(label, []).extend(cuts)
    # offcut optimization: nest partial pieces into shared 10-ft stock, per size
    for label, d in by.items():
        d["opt_sticks"] = len(ec.pack_sticks(lens[label]))
    grand = {k: sum(v[k] for v in by.values())
             for k in ("runs", "sticks", "couplers", "bends", "offsets", "saddles",
                       "len_mm", "opt_sticks")}
    return by, grand


def print_totals(rows):
    by, g = job_totals(rows)
    if not by:
        return
    ec.rule("=")
    print("  JOB TOTALS — material to order (conduit comes in 10-ft sticks)")
    print(f"   {'Conduit':<14}  {'Runs':>4}  {'Sticks':>6}  {'Couplers':>8}  "
          f"{'Bends':>5}  {'Conduit used':>13}")
    print(f"   {'-'*14}  {'-'*4}  {'-'*6}  {'-'*8}  {'-'*5}  {'-'*13}")
    for label in sorted(by):
        v = by[label]
        print(f"   {label:<14}  {v['runs']:>4}  {v['sticks']:>6}  {v['couplers']:>8}  "
              f"{v['bends']:>5}  {fmt_ft(v['len_mm']):>13}")
    if len(by) > 1:
        print(f"   {'-'*14}  {'-'*4}  {'-'*6}  {'-'*8}  {'-'*5}  {'-'*13}")
        print(f"   {'TOTAL':<14}  {g['runs']:>4}  {g['sticks']:>6}  {g['couplers']:>8}  "
              f"{g['bends']:>5}  {fmt_ft(g['len_mm']):>13}")
    if g["offsets"] or g["saddles"]:
        print(f"   of those bends: {g['offsets']} offset(s) and {g['saddles']} "
              f"saddle(s); the rest are single stubs/corners.")
    saved = g["sticks"] - g["opt_sticks"]
    if saved > 0:
        print(f"   Offcut optimization: buy {g['opt_sticks']} sticks vs {g['sticks']} "
              f"one-per-piece — saves {saved} stick(s) (~{saved * ec.STICK_FT:g} ft of stock).")
    print()


def print_report(info, rows, detail_n=5, summary_n=20):
    ec.rule("=")
    print("  CONDUIT BEND SCHEDULE")
    print(f"  source: {info['file']}   (Revit export, {info['schema']})")
    ec.rule("=")
    kinds = [r["kind"] for r in rows if r["kind"] != "?"]
    ods = [r["od_mm"] for r in rows if r["od_mm"]]
    dom_kind = max(set(kinds), key=kinds.count) if kinds else "?"
    dom_od = max(set(ods), key=ods.count) if ods else "?"
    print(f"  Conduit:  {dom_kind}, OD {dom_od} mm")
    print(f"  {info['n_runs']} runs total  ·  {info['n_bent']} with bends  ·  "
          f"{info['n_bends']} bends")
    print()

    bent = [r for r in rows if r["bends"]]
    bent.sort(key=lambda r: len(r["bends"]), reverse=True)

    print("  SUMMARY — runs with bends (most bends first)")
    print(f"   {'Run':>4}  {'Conduit':<10}  {'Length':>9}  {'Bends':>5}   Angles")
    print(f"   {'-'*4}  {'-'*10}  {'-'*9}  {'-'*5}   {'-'*28}")
    for r in bent[:summary_n]:
        angles = ",".join(f"{b['angle']:g}" for b in r["bends"])
        if len(angles) > 28:
            angles = angles[:25] + "..."
        print(f"   {r['run']:>4}  {r['kind']:<10}  {fmt_ft(r['length_mm']):>9}  "
              f"{len(r['bends']):>5}   {angles}")
    if len(bent) > summary_n:
        print(f"   ... and {len(bent) - summary_n} more (full list in conduit_runs.csv)")
    print()

    print(f"  DETAIL — the {min(detail_n, len(bent))} most complex runs "
          f"(every run is in conduit_bends.csv)")
    for r in bent[:detail_n]:
        print()
        print(f"  Run {r['run']} — {r['kind']}, {fmt_ft(r['length_mm'])} total, "
              f"{len(r['bends'])} bends")
        print(f"     {'bend':>4}   {'feed before':>12}   {'angle':>6}   {'roll/turn':>9}")
        print(f"     {'-'*4}   {'-'*12}   {'-'*6}   {'-'*9}")
        for j, b in enumerate(r["bends"], 1):
            roll = "—" if j == 1 else f"{b['rotate']:g}°"
            print(f"     {j:>4}   {fmt_ft(b['advance']):>12}   {b['angle']:>5g}°   {roll:>9}")
        print(f"     {'end':>4}   {fmt_ft(r['tail_mm']):>12}   {'(tail straight)':>18}")
        ops = ec.classify_ops(r["bends"])
        print("     as ops:  " + "  ·  ".join(fmt_op(o) for o in ops))
    print()

    # how the most complex run is cut into 10-ft sticks (couplers in straights)
    if bent and bent[0].get("pieces"):
        r = bent[0]
        size = ec.trade_size_for_od(r["od_mm"])
        rad = ec.bend_radius_mm(r["od_mm"])
        deduct = (f'  feeds take-up corrected for {size}" shoe '
                  f"(R {rad / MM_PER_FT * 12:.1f} in)" if rad else "")
        print(f"  FABRICATION — Run {r['run']} cut into {len(r['pieces'])} sticks "
              f"(≤10 ft; couplers in straights).{deduct}")
        print(f"               Die: load the {ec.die_label(r['kind'], r['od_mm'])} shoe "
              f"on the 555.   Full list in conduit_pieces.csv")
        for i, p in enumerate(r["pieces"], 1):
            cpl = ("cplr" if p["start_coupler"] else "free") + "→" + \
                  ("cplr" if p["end_coupler"] else "free")
            steps = " ; ".join(f"feed {fmt_ftin(b['feed'])} → {b['angle']:g}°"
                               f"({roll_label(b['rotate'], b.get('roll_dir', 0))})"
                               for b in p["bends"]) or "straight"
            print(f"     piece {i:>2} [cut {fmt_ft(p.get('developed_mm', p['length_mm'])):>7}, "
                  f"{cpl}]: {steps} ; tail {fmt_ftin(p['tail_mm'])}")
        print()

    print_totals(rows)


def write_csvs(rows, runs_csv=None, bends_csv=None):
    runs_csv = runs_csv or os.path.join(HERE, "conduit_runs.csv")
    bends_csv = bends_csv or os.path.join(HERE, "conduit_bends.csv")
    with open(runs_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", "conduit", "outer_diameter_mm", "length_ft", "length_mm",
                    "num_bends", "bend_angles_deg"])
        for r in rows:
            w.writerow([r["run"], r["kind"], r["od_mm"],
                        round(r["length_mm"] / MM_PER_FT, 2), r["length_mm"],
                        len(r["bends"]), " ".join(f"{b['angle']:g}" for b in r["bends"])])
    with open(bends_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", "bend_no", "feed_before_ft", "feed_before_mm",
                    "angle_deg", "roll_deg", "roll_dir"])
        for r in rows:
            for j, b in enumerate(r["bends"], 1):
                roll = 0 if j == 1 else b["rotate"]
                w.writerow([r["run"], j, round(b["advance"] / MM_PER_FT, 2),
                            b["advance"], b["angle"], roll,
                            roll_dir_word(roll, b.get("roll_dir", 0))])
    return runs_csv, bends_csv


def write_pieces_csv(rows, pieces_csv=None):
    """One row per physical conduit piece (stick), with its bend instructions."""
    pieces_csv = pieces_csv or os.path.join(HERE, "conduit_pieces.csv")
    with open(pieces_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", "piece", "pieces_in_run", "length_ft", "cut_length_ft",
                    "start_coupler", "end_coupler", "num_bends", "operations",
                    "instructions"])
        for r in rows:
            pcs = r.get("pieces") or []
            for i, p in enumerate(pcs, 1):
                # feeds are take-up corrected (deduct applied); cut_length is the
                # developed material to cut for this stick.
                steps = [f"feed {fmt_ftin(b['feed'])}, bend {b['angle']:g}"
                         f" ({roll_label(b['rotate'], b.get('roll_dir', 0))})"
                         for b in p["bends"]]
                steps.append(f"tail {fmt_ftin(p['tail_mm'])}")
                ops = "; ".join(fmt_op(o) for o in
                                ec.classify_ops(p["bends"], span_key="feed"))
                w.writerow([r["run"], i, len(pcs), round(p["length_mm"]/MM_PER_FT, 2),
                            round(p.get("developed_mm", p["length_mm"])/MM_PER_FT, 2),
                            int(p["start_coupler"]), int(p["end_coupler"]),
                            len(p["bends"]), ops, " ; ".join(steps)])
    return pieces_csv


def write_cutlist_csv(rows, cutlist_csv=None):
    """The offcut-optimized CUT PLAN: one row per raw 10-ft stick to buy, listing
    which pieces to cut from it (as run.piece @ length) and the offcut left over.
    Grouped by conduit size — this is how a shop cuts stock with least waste."""
    cutlist_csv = cutlist_csv or os.path.join(HERE, "conduit_cutlist.csv")
    by_size = {}
    for r in rows:
        size = ec.trade_size_for_od(r["od_mm"])
        label = f'{r["kind"]} {size}"' if size else r["kind"]
        for i, p in enumerate(r.get("pieces") or [], 1):
            length = p.get("developed_mm", p.get("length_mm", 0.0))
            by_size.setdefault(label, []).append((f'{r["run"]}.{i}', length))
    with open(cutlist_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["conduit", "raw_stick", "num_pieces", "pieces (run.piece @ length)",
                    "offcut_ft"])
        for label in sorted(by_size):
            sticks = ec.pack_labeled(by_size[label])
            for n, stick in enumerate(sticks, 1):
                used = sum(L for _, L in stick)
                cuts = "; ".join(f"{lab} @ {fmt_ftin(L)}" for lab, L in stick)
                w.writerow([label, n, len(stick), cuts,
                            round((ec.STICK_MM - used) / MM_PER_FT, 2)])
    return cutlist_csv


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    info, rows = run_rows(path)
    print_report(info, rows)
    runs_csv, bends_csv = write_csvs(rows)
    pieces_csv = write_pieces_csv(rows)
    print(f"  Spreadsheets written:")
    print(f"    {os.path.relpath(runs_csv)}   (one row per conduit run)")
    print(f"    {os.path.relpath(bends_csv)}   (one row per bend)")
    print(f"    {os.path.relpath(pieces_csv)}   (one row per 10-ft stick)")
    print()


if __name__ == "__main__":
    main()
