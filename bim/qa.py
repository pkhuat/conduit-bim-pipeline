"""Data-health / QA report — which runs need a human look before fabricating.

The pipeline is honest about what it can't cleanly resolve; this collects those
flags per run so a customer or shop reviews the handful that matter instead of
trusting 200 runs blindly. It flags three things:

  - odd angles   — bends that aren't standard trade angles (kept honest, not
                   forced to a trade angle), so someone confirms how to bend them.
  - coupler warn — a run where no valid coupler spot could be placed within a
                   stick (bends too close / straights too short).
  - drift        — the recipe, rebuilt, lands more than a threshold off the model
                   (round-trip validation), usually a near-trade snap on a long run.

    python3 bim/qa.py                          # the sample building
    python3 bim/qa.py bim/samples/conduit_dtv.ifc

process.py calls flag_rows()/write_health() directly with rows it already has, so
the IFC isn't re-parsed there.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_conduit as ec
import bend_report as br
import validate as V

DEFAULT = os.path.join(os.path.dirname(__file__), "samples", "sample_elec.ifc")
DRIFT_FLAG_MM = 100.0        # flag a run whose recipe rebuilds > ~4 in off the model


def _is_trade(angle, tol=0.05):
    return any(abs(angle - t) <= tol for t in ec.TRADE_ANGLES)


def flag_rows(rows, dev_by_run):
    """Pure logic: from per-run rows (br.run_rows) and a {run: max_dev_mm} map,
    return the flagged runs, each {run, kind, issues:[...]}."""
    flagged = []
    for r in rows:
        issues = []
        odd = [b["angle"] for b in r["bends"] if not _is_trade(b["angle"])]
        if odd:
            issues.append("odd angle: " + ", ".join(f"{a:g}°" for a in odd))
        if r.get("piece_warnings"):
            issues.append("coupler: " + "; ".join(r["piece_warnings"]))
        dev = dev_by_run.get(r["run"], 0.0)
        if dev > DRIFT_FLAG_MM:
            issues.append(f"drift: recipe rebuilds {dev / 25.4:.1f} in off the model")
        if issues:
            flagged.append({"run": r["run"], "kind": r["kind"], "issues": issues})
    return flagged


def counts(flagged):
    """(odd, coupler, drift) run counts for a flagged list."""
    tally = lambda kind: sum(1 for f in flagged
                             if any(i.startswith(kind) for i in f["issues"]))
    return tally("odd"), tally("coupler"), tally("drift")


def render(file_name, n_runs, flagged):
    """The full data-health report as text (used for stdout and the health file)."""
    n_odd, n_cpl, n_dft = counts(flagged)
    out = [
        "=" * 66,
        "  DATA HEALTH — review before fabricating",
        f"  source: {file_name}   ({n_runs} runs, {len(flagged)} need review)",
        "=" * 66,
        f"  odd angles:  {n_odd} run(s)      couplers: {n_cpl}      drift: {n_dft}",
        "",
    ]
    if not flagged:
        out.append("  All runs clean — every bend a trade angle, no warnings, no drift.")
        return "\n".join(out)
    out.append(f"   {'Run':>4}  {'Conduit':<12}  Issue(s)")
    out.append(f"   {'-'*4}  {'-'*12}  {'-'*44}")
    for f in sorted(flagged, key=lambda f: f["run"]):
        first, *rest = f["issues"]
        out.append(f"   {f['run']:>4}  {f['kind']:<12}  {first}")
        out.extend(f"   {'':>4}  {'':<12}  {extra}" for extra in rest)
    out += ["",
            "  Odd angles are kept honest (not faked to a trade angle) — confirm how",
            "  to bend them. Drift is the trade-angle cleanup; couplers may need a re-cut."]
    return "\n".join(out)


def write_health(out_path, file_name, n_runs, flagged):
    with open(out_path, "w") as fh:
        fh.write(render(file_name, n_runs, flagged) + "\n")
    return out_path


def audit(path):
    """Standalone: parse the IFC and flag runs. Returns (info, rows, flagged)."""
    info, rows = br.run_rows(path)
    _, devs = V.run_deviations(path)
    flagged = flag_rows(rows, {d["run"]: d["max_dev_mm"] for d in devs})
    return info, rows, flagged


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    info, rows, flagged = audit(path)
    print(render(info["file"], len(rows), flagged))


if __name__ == "__main__":
    main()
