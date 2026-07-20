"""Draw each conduit run as a simple diagram showing its bends.

    python3 bim/bend_diagram.py                          # the sample building
    python3 bim/bend_diagram.py bim/samples/conduit_dtv.ifc
    python3 bim/bend_diagram.py bim/samples/sample_elec.ifc 12   # top 12 runs

Writes a single self-contained HTML file (bim/diagrams.html) with one little 3D
sketch per conduit run: the centerline drawn in an isometric view, a dot at every
bend labeled with its angle, and the start/end marked. Open it in any browser.
This is the picture that goes next to the bend schedule from bend_report.py.
"""

import html
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ifcopenshell
import ifcopenshell.util.unit
import extract_conduit as ec

DEFAULT = os.path.join(os.path.dirname(__file__), "samples", "sample_elec.ifc")
OUT = os.path.join(os.path.dirname(__file__), "diagrams.html")
MM_PER_FT = 304.8
W, H, MARGIN = 560, 380, 46
# one color per 10-ft stick, cycled; chosen distinct from the bend (red) and
# start/end (green) markers so the sticks read as separate pieces.
STICK_COLORS = ("#2b6cb0", "#805ad5", "#d69e2e", "#319795", "#dd6b20", "#b83280", "#4a5568")


def cleaned_runs(path, top):
    model = ifcopenshell.open(path)
    scale = ifcopenshell.util.unit.calculate_unit_scale(model) * 1000.0
    segs, fits, _ = ec.conduit_elements(model)
    runs = ec.reconstruct_runs(model, segs, fits, scale=scale)

    out = []
    for i, (poly, run_segs) in enumerate(runs, 1):
        verts = ec.drop_near_straight(ec.simplify_polyline(poly, ec.SIMPLIFY_TOL), ec.MIN_BEND_DEG)
        if len(verts) < 3:
            continue                       # straight runs have nothing to draw
        angles = []
        for k in range(1, len(verts) - 1):
            a = ec.angle_between(ec.sub(verts[k], verts[k - 1]),
                                 ec.sub(verts[k + 1], verts[k]))
            angles.append(round(ec.snap_to_trade(a), 1))
        seg = run_segs[0] if run_segs else None
        # cut the run into 10-ft sticks (same logic as the bend schedule) so the
        # picture shows where the couplers fall; cut positions = cumulative spans.
        od = ec.outer_diameter(seg) if seg else None
        od_mm = round(od * scale, 1) if od else None
        bends, _, tail = ec.derive_bends(verts)
        pieces, _ = ec.split_into_pieces(bends, tail, radius_mm=ec.bend_radius_mm(od_mm))
        cuts, acc = [], 0.0
        for pc in pieces[:-1]:
            acc += pc["length_mm"]
            cuts.append(acc)
        out.append({
            "run": i,
            "kind": ec.conduit_kind(seg) if seg else "?",
            "length_ft": ec.path_length(verts) / MM_PER_FT,
            "verts": verts,
            "angles": angles,
            "cuts": cuts,
            "sticks": len(pieces),
        })
    out.sort(key=lambda r: len(r["angles"]), reverse=True)
    return os.path.basename(path), out[:top]


def iso(pt):
    """Isometric 3D->2D so vertical and horizontal bends both show."""
    x, y, z = pt
    return ((x - y) * 0.866, (x + y) * 0.5 - z)


def projector(verts):
    """Return to_screen(pt): maps any 3D point to canvas coords, scaled to fit
    `verts`. Points that lie ON the polyline (the coupler cuts) project onto the
    drawn line, because the isometric transform is affine."""
    P = [iso(v) for v in verts]
    xs = [p[0] for p in P]
    ys = [p[1] for p in P]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    s = min((W - 2 * MARGIN) / (maxx - minx or 1), (H - 2 * MARGIN) / (maxy - miny or 1))

    def to_screen(pt):
        X, Y = iso(pt)
        return (MARGIN + (X - minx) * s, H - (MARGIN + (Y - miny) * s))

    return to_screen


def split_polyline(verts, cuts):
    """Split a 3D polyline into one sub-polyline per 10-ft stick, cutting at the
    arc-length distances in `cuts` (mm along the centerline). Returns
    (sticks, coupler_points): `sticks` is a list of vertex lists with the cut
    boundaries interpolated in; `coupler_points` is the 3D point at each cut."""
    seglen = [ec.norm(ec.sub(verts[i + 1], verts[i])) for i in range(len(verts) - 1)]
    cum = [0.0]
    for L in seglen:
        cum.append(cum[-1] + L)
    total = cum[-1]

    def point_at(d):
        if d <= 0:
            return tuple(verts[0])
        if d >= total:
            return tuple(verts[-1])
        for i in range(len(seglen)):
            if cum[i] <= d <= cum[i + 1]:
                t = (d - cum[i]) / (seglen[i] or 1.0)
                a, b = verts[i], verts[i + 1]
                return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))
        return tuple(verts[-1])

    bounds = [0.0] + list(cuts) + [total]
    sticks = []
    for s in range(len(bounds) - 1):
        lo, hi = bounds[s], bounds[s + 1]
        stick = [point_at(lo)]
        for i in range(len(verts)):
            if lo < cum[i] < hi:
                stick.append(tuple(verts[i]))
        stick.append(point_at(hi))
        sticks.append(stick)
    return sticks, [point_at(c) for c in cuts]


def _unit2(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def _label(x, y, text, color, size=12, anchor="middle"):
    """Text with a white halo so it stays readable over the conduit line."""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-family="sans-serif" '
            f'text-anchor="{anchor}" dominant-baseline="middle" paint-order="stroke" '
            f'stroke="#ffffff" stroke-width="3.2" fill="{color}">{text}</text>')


def place_labels(P, angles, reserved=()):
    """Position each bend's angle label near its corner, nudging it out (and, if
    needed, to the corner's other side) so labels — and the reserved start/end
    labels — don't pile up when bends cluster. Returns
    [(dot_x, dot_y, label_x, label_y, angle)]; a label that ends up far from its
    dot gets a leader line drawn to it in svg_for."""
    placed = list(reserved)
    out = []
    MINSEP, STEP, DMAX = 21.0, 6.0, 46.0
    for k in range(1, len(P) - 1):
        x, y = P[k]
        v1 = _unit2(P[k], P[k - 1])
        v2 = _unit2(P[k], P[k + 1])
        bx, by = v1[0] + v2[0], v1[1] + v2[1]
        n = math.hypot(bx, by)
        if n < 1e-3:                       # straight-through: use a perpendicular
            din = _unit2(P[k - 1], P[k])
            bx, by, n = -din[1], din[0], 1.0
        bx, by = bx / n, by / n
        chosen = None
        for dx, dy in ((bx, by), (-bx, -by)):     # corner interior first, then outside
            d = 16.0
            while d <= DMAX:
                lx, ly = x + dx * d, y + dy * d
                if all(math.hypot(lx - px, ly - py) >= MINSEP for px, py in placed):
                    chosen = (lx, ly)
                    break
                d += STEP
            if chosen:
                break
        if chosen is None:                 # crowded: take the farthest interior spot
            chosen = (x + bx * DMAX, y + by * DMAX)
        placed.append(chosen)
        out.append((x, y, chosen[0], chosen[1], angles[k - 1]))
    return out


def svg_for(run):
    to_screen = projector(run["verts"])
    p = [to_screen(v) for v in run["verts"]]
    sticks, couplers = split_polyline(run["verts"], run["cuts"])
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fbfbfd" stroke="#e3e3ea"/>')
    # one colored polyline per 10-ft stick (adjacent sticks get different colors)
    for i, stick in enumerate(sticks):
        sp = " ".join(f"{x:.1f},{y:.1f}" for x, y in (to_screen(v) for v in stick))
        parts.append(f'<polyline points="{sp}" fill="none" stroke="{STICK_COLORS[i % len(STICK_COLORS)]}" '
                     f'stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
    # start / end label anchors — reserve them so bend labels don't land on them
    sx, sy = p[0]
    ex, ey = p[-1]
    d0 = _unit2(p[0], p[1])
    dn = _unit2(p[-2], p[-1])
    start_lbl = (sx - d0[0] * 20, sy - d0[1] * 20)
    end_lbl = (ex + dn[0] * 20, ey + dn[1] * 20)
    labels = place_labels(p, run["angles"], reserved=[start_lbl, end_lbl])

    # leader lines first (under everything) for any label nudged away from its dot
    for x, y, lx, ly, ang in labels:
        if math.hypot(lx - x, ly - y) > 13:
            parts.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" '
                         f'stroke="#cbd5e0" stroke-width="1"/>')
    # couplers — hollow marks on the straights where one stick joins the next
    for cp in couplers:
        cx, cy = to_screen(cp)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.8" fill="#ffffff" '
                     f'stroke="#2d3748" stroke-width="1.6"/>')
    # bend dots, then labels on top (so the halo never sits under a dot)
    for x, y, lx, ly, ang in labels:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#e53e3e"/>')
    for x, y, lx, ly, ang in labels:
        parts.append(_label(lx, ly, f"{ang:g}&#176;", "#1a202c"))
    # start / end
    parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5" fill="#2f855a"/>')
    parts.append(_label(start_lbl[0], start_lbl[1], "start", "#2f855a"))
    parts.append(f'<rect x="{ex - 4:.1f}" y="{ey - 4:.1f}" width="8" height="8" fill="#2f855a"/>')
    parts.append(_label(end_lbl[0], end_lbl[1], "end", "#2f855a"))
    parts.append('</svg>')
    return "".join(parts)


def build_html(fname, runs):
    def short(name):
        m = re.search(r"\(([^)]+)\)", name or "")
        return m.group(1) if m else (name or "?")

    cards = []
    for r in runs:
        title = (f"Run {r['run']} &mdash; {html.escape(short(r['kind']))}"
                 f", {r['length_ft']:.1f} ft, {len(r['angles'])} bends, "
                 f"{r['sticks']} sticks")
        cards.append(f'<div class="card"><div class="ttl">{title}</div>{svg_for(r)}</div>')

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Conduit bend diagrams — {html.escape(fname)}</title>
<style>
 body{{font-family:sans-serif;background:#f0f0f4;margin:0;padding:24px;color:#1a202c}}
 h1{{font-size:20px}} .sub{{color:#555;margin-bottom:18px}}
 .grid{{display:flex;flex-wrap:wrap;gap:18px}}
 .card{{background:#fff;border:1px solid #e3e3ea;border-radius:10px;padding:10px;
        box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 .ttl{{font-size:14px;font-weight:600;margin:4px 6px 8px}}
</style></head><body>
<h1>Conduit bend diagrams &mdash; {html.escape(fname)}</h1>
<div class="sub">Top {len(runs)} runs by bend count. Each sketch is the conduit
centerline in 3D (isometric); <i style="color:#2f855a">green</i> = start/end,
<b style="color:#e53e3e">red dots</b> = bends (labeled with angle). Each
<b>color band is one 10-ft stick</b>; a <b>&#9711; hollow mark</b> is a coupler
where two sticks join (always on a straight). Feed lengths and rolls are in the
bend schedule / pieces.csv.</div>
<div class="grid">{''.join(cards)}</div>
</body></html>"""


def write_html(out_path, fname, runs):
    with open(out_path, "w") as fh:
        fh.write(build_html(fname, runs))
    return out_path


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    fname, runs = cleaned_runs(path, top)
    write_html(OUT, fname, runs)
    print(f"Wrote {os.path.relpath(OUT)} — {len(runs)} run diagram(s).")
    print(f"Open it:  open {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
