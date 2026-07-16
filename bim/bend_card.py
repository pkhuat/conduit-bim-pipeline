"""Per-stick BEND CARDS — a printable shop traveler for every stick that needs
bending.

Each card is one physical 10-ft stick drawn as a flat stretch-out: the conduit
laid out straight, the load end at 0, a red mark at each bend (labeled with its
angle and roll), the take-up-corrected feed on every segment, and the couplers
shown on the ends. Below the picture are the numbered steps in feet-and-inches —
the recipe a fabricator (or the Greenlee 555) follows for that stick.

Straight sticks need no card; they're summarized per run ("cut to 10 ft, couple").

    python3 bim/bend_card.py [file.ifc]      # writes bim/bend_cards.html

In the normal pipeline process.py calls build_cards_html(stem, rows) directly so
the run data is parsed only once.
"""

import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_conduit as ec
import bend_report as br

MM_PER_FT = 304.8
W, BAR_Y = 760, 80          # card SVG canvas width and the bar's y
X0, X1 = 70.0, W - 40.0     # bar runs from the load end (X0) to the tail end (X1)


def _t(x, y, text, color, size=12, weight="normal", anchor="middle"):
    """Halo'd SVG text so labels stay readable over the conduit bar."""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-family="sans-serif" '
            f'text-anchor="{anchor}" font-weight="{weight}" dominant-baseline="middle" '
            f'paint-order="stroke" stroke="#ffffff" stroke-width="3" fill="{color}">{text}</text>')


def stick_marks(piece):
    """(material_position_mm, bend) for each bend, measured along the cut stick
    from the load end: advance the feed, mark the bend, then the bend's arc is
    consumed before the next feed."""
    pos, marks = 0.0, []
    for b in piece["bends"]:
        pos += b["feed"]
        marks.append((pos, b))
        pos += b.get("arc_mm", 0.0)
    return marks


def _end_marker(x, coupled):
    """Coupler (hollow circle) or open end (small bar) drawn on the bar at x."""
    if coupled:
        return (f'<circle cx="{x:.1f}" cy="{BAR_Y:.1f}" r="4.5" fill="#ffffff" '
                f'stroke="#2d3748" stroke-width="1.8"/>')
    return (f'<line x1="{x:.1f}" y1="{BAR_Y - 7:.1f}" x2="{x:.1f}" y2="{BAR_Y + 7:.1f}" '
            f'stroke="#2f855a" stroke-width="3"/>')


def card_svg(piece, ops=None):
    cut = piece.get("developed_mm", piece["length_mm"]) or 1.0
    scale = (X1 - X0) / cut

    def x_of(pos):
        return X0 + pos * scale

    parts = [f'<svg viewBox="0 0 {W} 150" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<rect x="0" y="0" width="{W}" height="150" fill="#fbfbfd" stroke="#e3e3ea"/>')
    parts.append(f'<line x1="{X0:.1f}" y1="{BAR_Y}" x2="{X1:.1f}" y2="{BAR_Y}" '
                 f'stroke="#2b6cb0" stroke-width="6" stroke-linecap="round"/>')

    marks = stick_marks(piece)
    # brackets over the marks that make up an offset/saddle (multi-bend ops)
    for o in ops or []:
        if len(o["idx"]) < 2:
            continue
        x1, x2 = x_of(marks[o["idx"][0]][0]), x_of(marks[o["idx"][-1]][0])
        yb = BAR_Y - 52
        parts.append(f'<path d="M {x1:.1f} {yb + 5:.1f} V {yb:.1f} H {x2:.1f} V {yb + 5:.1f}" '
                     f'stroke="#805ad5" fill="none" stroke-width="1.3"/>')
        # concise label on the bracket (rise); full shrink/×multiplier is in the
        # operations line under the card header.
        short = (f"{o['angle']:g}&#176; offset ({br.fmt_ftin(o['rise_mm'])} rise)"
                 if o["type"] == "offset" else br.fmt_op(o))
        parts.append(_t((x1 + x2) / 2, yb - 8, short, "#6b46c1", 11, weight="600"))
    prev_x = X0
    for pos, b in marks:
        mx = x_of(pos)
        parts.append(_t((prev_x + mx) / 2, BAR_Y + 24, f"feed {br.fmt_ftin(b['feed'])}", "#4a5568"))
        parts.append(f'<line x1="{mx:.1f}" y1="{BAR_Y:.1f}" x2="{mx:.1f}" y2="{BAR_Y - 30:.1f}" '
                     f'stroke="#e53e3e" stroke-width="2"/>')
        parts.append(f'<circle cx="{mx:.1f}" cy="{BAR_Y:.1f}" r="4.5" fill="#e53e3e"/>')
        parts.append(_t(mx, BAR_Y - 40, f"{b['angle']:g}&#176;", "#1a202c", 15, weight="700"))
        w = br.roll_dir_word(b["rotate"], b.get("roll_dir", 0))
        roll = f"roll {b['rotate']:g}&#176;" + (f" {w}" if w else "")
        parts.append(_t(mx, BAR_Y + 44, roll, "#805ad5", 11))
        prev_x = mx
    # tail segment + ends
    parts.append(_t((prev_x + X1) / 2, BAR_Y + 24, f"tail {br.fmt_ftin(piece['tail_mm'])}", "#4a5568"))
    parts.append(_end_marker(X0, piece["start_coupler"]))
    parts.append(_end_marker(X1, piece["end_coupler"]))
    parts.append(_t(X0, BAR_Y - 22, "load &#9654;", "#2f855a", 11, anchor="start"))
    parts.append(_t(X0, 138, "coupler" if piece["start_coupler"] else "open end", "#718096", 10, anchor="start"))
    parts.append(_t(X1, 138, "coupler" if piece["end_coupler"] else "open end", "#718096", 10, anchor="end"))
    parts.append(_t(X1, BAR_Y - 40, f"cut {br.fmt_ftin(cut)}", "#2f855a", 11, anchor="end", weight="600"))
    parts.append('</svg>')
    return "".join(parts)


def steps_html(piece):
    lis = ["<li>Load the leading end at the bender zero "
           f"({'coupler joint' if piece['start_coupler'] else 'open end'}).</li>"]
    for b in piece["bends"]:
        w = br.roll_dir_word(b["rotate"], b.get("roll_dir", 0))
        roll = f"{b['rotate']:g}&deg;" + (f" {w}" if w else "")
        lis.append(f"<li>Feed <b>{br.fmt_ftin(b['feed'])}</b>, "
                   f"bend <b>{b['angle']:g}&deg;</b> (roll {roll}).</li>")
    tail_end = "couple to the next stick" if piece["end_coupler"] else "open end"
    lis.append(f"<li>Tail <b>{br.fmt_ftin(piece['tail_mm'])}</b> remaining — {tail_end}.</li>")
    return "<ol>" + "".join(lis) + "</ol>"


def build_cards_html(stem, rows):
    """Return the bend-cards HTML page for a processed file's `rows`
    (br.run_rows output). One card per bent stick, grouped by run."""
    kinds = [r["kind"] for r in rows if r["kind"] != "?"]
    dom_kind = max(set(kinds), key=kinds.count) if kinds else "?"
    n_bent = sum(1 for r in rows for p in (r.get("pieces") or []) if p["bends"])
    n_runs = sum(1 for r in rows if any(p["bends"] for p in (r.get("pieces") or [])))

    blocks = []
    for r in sorted(rows, key=lambda r: r["run"]):
        pieces = r.get("pieces") or []
        bent = [(i, p) for i, p in enumerate(pieces, 1) if p["bends"]]
        if not bent:
            continue
        size = ec.trade_size_for_od(r["od_mm"])
        straight = len(pieces) - len(bent)
        size_lbl = f'{size}"' if size else f'{r["od_mm"]} mm'
        blocks.append(
            f'<h2>Run {r["run"]} &mdash; {html.escape(br.short_kind(r["kind"]))} '
            f'{size_lbl} &middot; {len(pieces)} sticks ({len(bent)} to bend, '
            f'{straight} straight)</h2>')
        for i, p in bent:
            cut = p.get("developed_mm", p["length_mm"])
            head = (f'Run {r["run"]} &middot; Stick {i} of {len(pieces)} &middot; '
                    f'cut {br.fmt_ftin(cut)} &middot; {len(p["bends"])} bend(s)')
            # classify this stick's bends into trade operations (feed = span within
            # the stick, so an offset split by a coupler falls back to two bends)
            ops = ec.classify_ops(p["bends"], span_key="feed")
            ops_line = "  &middot;  ".join(br.fmt_op(o) for o in ops)
            blocks.append(f'<div class="card"><div class="hd">{head}</div>'
                          f'<div class="ops">{ops_line}</div>'
                          f'{card_svg(p, ops)}{steps_html(p)}</div>')
        if straight:
            blocks.append(f'<div class="note">+ {straight} straight stick(s) on this '
                          f'run — cut to 10 ft and couple, no bending.</div>')

    body = "".join(blocks) or "<div class='note'>No bent sticks — every run is straight.</div>"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Bend cards &mdash; {html.escape(stem)}</title>
<style>
 body{{font-family:sans-serif;background:#f0f0f4;margin:0;padding:24px;color:#1a202c}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#555;margin-bottom:18px}}
 h2{{font-size:15px;margin:22px 0 8px;color:#2d3748}}
 .card{{background:#fff;border:1px solid #e3e3ea;border-radius:10px;padding:12px 14px;
        margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);break-inside:avoid}}
 .hd{{font-size:14px;font-weight:600;margin-bottom:2px}}
 .ops{{font-size:12px;color:#6b46c1;font-weight:600;margin-bottom:6px}}
 ol{{margin:6px 0 2px;padding-left:22px;font-size:13px;line-height:1.7}}
 .note{{color:#718096;font-size:12px;margin:2px 0 10px;font-style:italic}}
 @media print{{body{{background:#fff;padding:0}} .card{{box-shadow:none}}}}
</style></head><body>
<h1>Bend cards &mdash; {html.escape(stem)} ({dom_kind})</h1>
<div class="sub">{n_bent} stick(s) to bend across {n_runs} run(s). Each stick is a
flat stretch-out: load end at left, <b style="color:#e53e3e">red marks</b> = bends
(angle above, roll below), feeds in feet-and-inches, <b>&#9711;</b> = coupler.
Trade operations (<b style="color:#6b46c1">offsets/saddles</b>) are named under the
header and bracketed over their marks. Take-up corrected. Print this — one card per
stick to fabricate.</div>
{body}
</body></html>"""


def write_cards_html(out_path, stem, rows):
    with open(out_path, "w") as fh:
        fh.write(build_cards_html(stem, rows))
    return out_path


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else br.DEFAULT
    stem = os.path.splitext(os.path.basename(path))[0]
    info, rows = br.run_rows(path)
    out = os.path.join(os.path.dirname(__file__), "bend_cards.html")
    write_cards_html(out, stem, rows)
    n = sum(1 for r in rows for p in (r.get("pieces") or []) if p["bends"])
    print(f"Wrote {os.path.relpath(out)} — {n} bend card(s).")
    print(f"Open it:  open {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
