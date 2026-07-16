"""One command: turn any IFC export into all the conduit deliverables.

    python3 bim/process.py path/to/anything.ifc      # process one file
    python3 bim/process.py --watch [folder]          # auto-process dropped files

For the given file it prints the bend schedule and writes, into bim/out/ named
after the input file (so a new IFC never overwrites an old one's results):

    <name>_runs.csv       — one row per conduit run (size, length, # bends)
    <name>_bends.csv      — one row per bend (feed length, angle, roll)
    <name>_diagrams.html  — a 3D sketch of each run with its bends labeled
    <name>_job.json       — the most complex run as a machine bend job (run in the sim)

Re-run it on a new IFC and that file's outputs appear/refresh automatically.
With --watch, drop any .ifc into the folder (default bim/incoming/) and it gets
processed on its own — no command needed.

When it finishes it opens bim/out/index.html in your browser automatically; pass
--no-open to skip that (e.g. on a headless machine).
"""

import csv
import html
import json
import os
import re
import sys
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bend_report as br
import bend_diagram as bd
import bend_card as bc
import validate as V
import qa
import calibration as cal

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "out")
INDEX = os.path.join(OUTDIR, "index.html")
MM_PER_FT = 304.8


def open_in_browser(path):
    """Open a local file in the default browser (best-effort, never fatal)."""
    if os.path.exists(path):
        try:
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception:
            pass


def run_pieces(r):
    """Per-10-ft-stick machine pieces for one run (advance/rotate/roll_dir/angle),
    the take-up-corrected form the driver runs."""
    out = []
    for idx, p in enumerate(r.get("pieces") or [], 1):
        out.append({
            "piece": idx,
            "load": "coupler" if p["start_coupler"] else "open end",
            "end": "coupler" if p["end_coupler"] else "open end",
            "length_ft": round(p["length_mm"] / MM_PER_FT, 2),
            "cut_length_ft": round(p.get("developed_mm", p["length_mm"]) / MM_PER_FT, 2),
            # advance = take-up-corrected feed before each bend (machine ADVANCE axis);
            # roll_dir = signed roll direction (+1/-1/0) for the ROTATE axis
            "bends": [{"advance": b["feed"], "rotate": b["rotate"],
                       "roll_dir": b.get("roll_dir", 0), "angle": b["angle"]}
                      for b in p["bends"]],
            "tail_advance": p["tail_mm"],         # straight remaining after the last bend
        })
    return out


def process_one(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(OUTDIR, exist_ok=True)

    # 1) schedule + CSVs
    info, rows = br.run_rows(path)
    if not rows:
        print(f"  {os.path.basename(path)}: no conduit runs found "
              f"(no IfcCableCarrierSegment centerlines) — nothing to fabricate. "
              f"Is this an electrical model?")
        print()
        return
    br.print_report(info, rows)
    runs_csv = os.path.join(OUTDIR, f"{stem}_runs.csv")
    bends_csv = os.path.join(OUTDIR, f"{stem}_bends.csv")
    br.write_csvs(rows, runs_csv, bends_csv)
    pieces_csv = os.path.join(OUTDIR, f"{stem}_pieces.csv")
    br.write_pieces_csv(rows, pieces_csv)
    cutlist_csv = os.path.join(OUTDIR, f"{stem}_cutlist.csv")
    br.write_cutlist_csv(rows, cutlist_csv)

    # 2) diagrams + printable per-stick bend cards
    fname, druns = bd.cleaned_runs(path, 12)
    html_path = os.path.join(OUTDIR, f"{stem}_diagrams.html")
    bd.write_html(html_path, fname, druns)
    cards_path = os.path.join(OUTDIR, f"{stem}_cards.html")
    bc.write_cards_html(cards_path, stem, rows)

    # 3) machine job for the most complex run — per 10-ft stick, take-up corrected
    #    (load each stick at 0, advance, bend, roll). Runnable in the sim.
    job_path = None
    bent = [r for r in rows if r["bends"]]
    if bent:
        r = max(bent, key=lambda r: len(r["bends"]))
        pieces = run_pieces(r)
        job = {
            "name": f"{stem} — most complex conduit run (run {r['run']})",
            "description": "Per-10-ft-stick bend instructions: load each stick at "
                           "position 0, advance, bend, roll. Feeds are take-up "
                           "corrected; roll_dir is the signed roll direction (+1/-1, "
                           "right-hand rule about feed — confirm CW/CCW vs the machine). "
                           "Auto-derived from IFC; uncalibrated, not hardware-reviewed.",
            "units": "millimetres of conduit feed / degrees of turn - NOT motor steps",
            "calibrated": cal.CALIBRATED,     # steps/springback not yet measured on the machine
            "conduit": r["kind"],
            "die": br.ec.die_label(r["kind"], r["od_mm"]),
            "outer_diameter_mm": r["od_mm"],
            "bend_radius_mm": round(br.ec.bend_radius_mm(r["od_mm"]), 1),
            "stick_length_ft": br.ec.STICK_FT,
            "pieces": pieces,
        }
        job_path = os.path.join(OUTDIR, f"{stem}_job.json")
        json.dump(job, open(job_path, "w"), indent=2)

        # whole-building machine data: every bent run's per-stick pieces
        all_jobs = {
            "name": f"{stem} — all bent runs",
            "units": "millimetres of conduit feed / degrees of turn - NOT motor steps",
            "runs": [{"run": rr["run"], "conduit": rr["kind"],
                      "die": br.ec.die_label(rr["kind"], rr["od_mm"]),
                      "pieces": run_pieces(rr)} for rr in bent],
        }
        json.dump(all_jobs, open(os.path.join(OUTDIR, f"{stem}_all_jobs.json"), "w"), indent=2)

    # 4) data-health / QA — round-trip validate the recipe and flag runs to review
    _, devs = V.run_deviations(path)
    flagged = qa.flag_rows(rows, {d["run"]: d["max_dev_mm"] for d in devs})
    health_path = os.path.join(OUTDIR, f"{stem}_health.txt")
    qa.write_health(health_path, os.path.basename(path), len(rows), flagged)
    n_odd, n_cpl, n_dft = qa.counts(flagged)
    print(f"  DATA HEALTH — {len(flagged)} of {len(rows)} runs need review "
          f"({n_odd} odd angle, {n_dft} drift, {n_cpl} coupler).  See {stem}_health.txt")
    print()

    write_index(OUTDIR)                      # refresh the landing page

    rel = os.path.relpath
    print("  Outputs written:")
    print(f"    {rel(runs_csv)}       (one row per conduit)")
    print(f"    {rel(bends_csv)}      (one row per bend)")
    print(f"    {rel(pieces_csv)}     (one row per 10-ft stick + its bend instructions)")
    print(f"    {rel(cutlist_csv)}    (offcut-optimized cut plan: pieces per raw stick)")
    print(f"    {rel(html_path)}  (open in a browser)")
    print(f"    {rel(cards_path)}     (printable per-stick bend cards)")
    print(f"    {rel(health_path)}      (data-health: runs to review)")
    if job_path:
        print(f"    {rel(job_path)}       (run it: python3 run_demo.py {rel(job_path)})")
    print(f"    {rel(os.path.join(OUTDIR, 'index.html'))}        (all jobs — open this one)")
    print()


def write_index(outdir):
    """(Re)write bim/out/index.html — a landing page listing every processed job
    with links to its diagram and CSVs, plus a quick count of conduits and bends.
    Refreshed after each file so it always reflects what's in the folder."""
    stems = sorted(n[:-len("_runs.csv")] for n in os.listdir(outdir)
                   if n.endswith("_runs.csv"))
    body = []
    for stem in stems:
        n_cond = n_bends = n_sticks = 0
        total_ft = 0.0
        conduit = od = "?"
        try:
            with open(os.path.join(outdir, f"{stem}_runs.csv"), newline="") as fh:
                data = list(csv.DictReader(fh))
            n_cond = len(data)
            n_bends = sum(int(r["num_bends"]) for r in data if r.get("num_bends"))
            total_ft = sum(float(r["length_ft"]) for r in data if r.get("length_ft"))
            kinds = [r["conduit"] for r in data if r.get("conduit")]
            ods = [r["outer_diameter_mm"] for r in data if r.get("outer_diameter_mm")]
            conduit = max(set(kinds), key=kinds.count) if kinds else "?"
            od = max(set(ods), key=ods.count) if ods else "?"
        except Exception:
            pass
        try:
            with open(os.path.join(outdir, f"{stem}_pieces.csv"), newline="") as fh:
                n_sticks = sum(1 for _ in csv.reader(fh)) - 1
        except Exception:
            pass
        n_review = None
        try:
            with open(os.path.join(outdir, f"{stem}_health.txt")) as fh:
                m = re.search(r"(\d+)\s+need review", fh.read())
                n_review = int(m.group(1)) if m else None
        except Exception:
            pass

        def link(suffix, label):
            f = f"{stem}{suffix}"
            return (f'<a href="{f}">{label}</a>' if os.path.exists(os.path.join(outdir, f))
                    else f'<span class="x">{label}</span>')

        files = " · ".join([link("_diagrams.html", "diagram"),
                            link("_cards.html", "bend cards"),
                            link("_health.txt", "health"),
                            link("_runs.csv", "runs.csv"),
                            link("_bends.csv", "bends.csv"),
                            link("_pieces.csv", "pieces.csv"),
                            link("_cutlist.csv", "cutlist.csv"),
                            link("_job.json", "job.json")])
        n_couplers = max(max(n_sticks, 0) - n_cond, 0)   # k sticks per run -> k-1 couplers
        review = ("—" if n_review is None
                  else f"<span class='ok'>0</span>" if n_review == 0
                  else f"<a href='{stem}_health.txt' class='rev'>{n_review}</a>")
        body.append(f"<tr><td class='nm'>{html.escape(stem)}</td>"
                    f"<td>{html.escape(str(conduit))} ({od} mm)</td>"
                    f"<td class='n'>{n_cond}</td><td class='n'>{n_bends}</td>"
                    f"<td class='n'>{max(n_sticks, 0)}</td>"
                    f"<td class='n'>{n_couplers}</td>"
                    f"<td class='n'>{total_ft:.0f}</td>"
                    f"<td class='n'>{review}</td>"
                    f"<td>{files}</td></tr>")

    rows_html = "".join(body) or ("<tr><td colspan='9' style='color:#888'>"
                                  "No jobs yet — process an IFC file.</td></tr>")
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Conduit jobs</title><style>
 body{{font-family:sans-serif;background:#f0f0f4;margin:0;padding:24px;color:#1a202c}}
 h1{{font-size:20px}} .sub{{color:#555;margin-bottom:16px}}
 table{{border-collapse:collapse;background:#fff;border:1px solid #e3e3ea;
        border-radius:10px;overflow:hidden;min-width:680px}}
 th,td{{padding:9px 14px;text-align:left;border-bottom:1px solid #eee;font-size:14px}}
 th{{background:#fafafe;color:#444;font-size:12px;text-transform:uppercase}}
 td.nm{{font-weight:600}} td.n{{text-align:right}}
 a{{color:#2b6cb0;text-decoration:none}} a:hover{{text-decoration:underline}}
 .x{{color:#bbb}} .rev{{color:#c05621;font-weight:700}} .ok{{color:#2f855a}}
</style></head><body>
<h1>Conduit jobs</h1>
<div class="sub">Every IFC processed into bim/out/. Click a job's diagram, bend cards, health, or CSVs.
Sticks = 10-ft pieces to buy; Couplers = joints between them; Review = runs needing a human look.</div>
<table><tr><th>Job (IFC)</th><th>Conduit</th><th>Conduits</th><th>Bends</th>
<th>Sticks</th><th>Couplers</th><th>Total ft</th><th>Review</th><th>Files</th></tr>
{rows_html}</table></body></html>"""
    with open(os.path.join(outdir, "index.html"), "w") as fh:
        fh.write(doc)


def scan_once(folder, seen):
    """Process every .ifc in `folder` that is new or changed since last scan."""
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".ifc"):
            continue
        p = os.path.join(folder, name)
        mtime = os.path.getmtime(p)
        if seen.get(p) != mtime:
            seen[p] = mtime
            print(f"\n>>> processing {name}")
            try:
                process_one(p)
            except Exception as e:
                print(f"  error processing {name}: {e}")


def watch(folder, interval=2.0):
    """Poll `folder` forever and process any .ifc file that is new or has changed."""
    os.makedirs(folder, exist_ok=True)
    print(f"Watching {os.path.relpath(folder)}/ for .ifc files — drop one in.  "
          f"(Ctrl+C to stop)")
    seen = {}
    while True:
        scan_once(folder, seen)
        time.sleep(interval)


def main():
    args = sys.argv[1:]
    auto_open = "--no-open" not in args        # auto-open the index unless suppressed
    args = [a for a in args if a != "--no-open"]

    if args and args[0] == "--index":          # just rebuild the landing page
        os.makedirs(OUTDIR, exist_ok=True)
        write_index(OUTDIR)
        print(f"Wrote {os.path.relpath(INDEX)}")
        if auto_open:
            open_in_browser(INDEX)
        return
    if args and args[0] in ("--watch", "--once"):
        folder = args[1] if len(args) > 1 else os.path.join(HERE, "incoming")
        os.makedirs(folder, exist_ok=True)
        if args[0] == "--once":
            scan_once(folder, {})          # batch-process a folder, then exit
            if auto_open:
                open_in_browser(INDEX)
        else:
            os.makedirs(OUTDIR, exist_ok=True)
            write_index(OUTDIR)            # make sure a page exists, then open once
            if auto_open:
                open_in_browser(INDEX)
            watch(folder)
        return
    if not args:
        print("usage: python3 bim/process.py FILE.ifc | --once [folder] | "
              "--watch [folder] | --index    [--no-open]")
        sys.exit(2)
    path = args[0]
    if not os.path.exists(path):
        print(f"file not found: {path}")
        sys.exit(2)
    process_one(path)
    if auto_open:
        open_in_browser(INDEX)


if __name__ == "__main__":
    main()
