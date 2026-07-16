"""Web front door for the conduit pipeline.

Drag-drop a Revit/BIM IFC export in the browser and get back the full
fabrication package — bend cards, diagrams, cut list, bill of materials, a
data-health report, and a machine job — rendered on a results page and
downloadable as a zip. Wraps the same `bim/process.py` the CLI runs.

    pip install flask
    python3 webapp/app.py        # then open http://127.0.0.1:5000

Simulation/office tool only; produces the machine-ready job, does not drive hardware.
"""

import csv
import io
import os
import re
import sys
import zipfile
import contextlib

from flask import (Flask, request, redirect, url_for, send_file,
                   send_from_directory, render_template_string, abort)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIM = os.path.join(ROOT, "bim")
OUT = os.path.join(BIM, "out")
UPLOADS = os.path.join(HERE, "uploads")
sys.path.insert(0, BIM)
import process  # noqa: E402  (the pipeline)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024   # accept up to 250 MB models


def _stem(filename):
    """A safe output stem from an uploaded filename."""
    base = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"[^A-Za-z0-9_.-]", "_", base) or "upload"


def read_stats(stem):
    """Summarize a processed job by reading its generated outputs (no re-parse)."""
    s = {"conduit": "?", "conduits": 0, "bends": 0, "sticks": 0, "total_ft": 0,
         "raw_sticks": 0, "review": 0, "flags": []}
    try:
        with open(os.path.join(OUT, f"{stem}_runs.csv"), newline="") as fh:
            data = list(csv.DictReader(fh))
        s["conduits"] = len(data)
        s["bends"] = sum(int(r["num_bends"]) for r in data if r.get("num_bends"))
        s["total_ft"] = round(sum(float(r["length_ft"]) for r in data if r.get("length_ft")))
        kinds = [r["conduit"] for r in data if r.get("conduit")]
        s["conduit"] = max(set(kinds), key=kinds.count) if kinds else "?"
    except Exception:
        pass
    for key, suffix in (("sticks", "_pieces.csv"), ("raw_sticks", "_cutlist.csv")):
        try:
            with open(os.path.join(OUT, f"{stem}{suffix}"), newline="") as fh:
                s[key] = max(sum(1 for _ in csv.reader(fh)) - 1, 0)
        except Exception:
            pass
    try:
        with open(os.path.join(OUT, f"{stem}_health.txt")) as fh:
            txt = fh.read()
        m = re.search(r"(\d+)\s+need review", txt)
        s["review"] = int(m.group(1)) if m else 0
        s["flags"] = [ln.strip() for ln in txt.splitlines()
                      if re.match(r"\s+\d+\s+\S", ln)][:40]
    except Exception:
        pass
    return s


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{{--navy:#12294d;--bg:#f4f5f8;--ok:#2f855a;--warn:#c05621}}
 *{{box-sizing:border-box}} body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;
   background:var(--bg);margin:0;color:#1a202c}}
 .wrap{{max-width:860px;margin:0 auto;padding:34px 20px}}
 h1{{color:var(--navy);font-size:24px;margin:0 0 4px}} .sub{{color:#556;margin-bottom:22px}}
 .drop{{border:2.5px dashed #9fb0c8;border-radius:14px;background:#fff;padding:44px 20px;
   text-align:center;transition:.15s}} .drop.hi{{border-color:var(--navy);background:#eef3fb}}
 .drop b{{color:var(--navy)}} input[type=file]{{display:none}}
 .btn{{background:var(--navy);color:#fff;border:0;border-radius:9px;padding:11px 22px;
   font-size:15px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}}
 .btn.g{{background:#fff;color:var(--navy);border:1.5px solid var(--navy)}}
 .row{{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px;align-items:center}}
 .tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:18px 0}}
 .tile{{background:#fff;border:1px solid #e3e6ee;border-radius:12px;padding:14px}}
 .tile .n{{font-size:26px;font-weight:700;color:var(--navy)}} .tile .l{{font-size:12px;color:#667}}
 .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}
 .card{{background:#fff;border:1px solid #e3e6ee;border-radius:12px;padding:16px;text-decoration:none;color:inherit}}
 .card:hover{{border-color:var(--navy);box-shadow:0 2px 10px rgba(0,0,0,.06)}}
 .card .t{{font-weight:700;color:var(--navy)}} .card .d{{font-size:12px;color:#667;margin-top:3px}}
 .banner{{border-radius:12px;padding:14px 16px;margin:18px 0}}
 .banner.warn{{background:#fff5ef;border:1px solid #f0c9ac}} .banner.ok{{background:#eefaf1;border:1px solid #bfe6cd}}
 .flags{{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#7a4a2a;max-height:160px;
   overflow:auto;margin-top:8px;white-space:pre-wrap}}
 code{{background:#eef;padding:1px 5px;border-radius:4px}}
 label.chk{{font-size:14px;color:#445;display:flex;gap:7px;align-items:center;cursor:pointer}}
</style></head><body><div class="wrap">{body}</div>{script}</body></html>"""

UPLOAD_BODY = """
<h1>Conduit Fabrication Pipeline</h1>
<div class="sub">Drop a Revit / BIM <b>.ifc</b> export &mdash; get bend cards, a cut list,
a bill of materials, a data-health report, and a machine job.</div>
<form id="f" method="post" action="/process" enctype="multipart/form-data">
  <label for="ifc"><div class="drop" id="drop">
    <div style="font-size:40px">&#128193;</div>
    <div><b>Drag &amp; drop</b> your <b>.ifc</b> here, or <b>click to browse</b></div>
    <div class="sub" id="fname" style="margin-top:8px">no file chosen</div>
  </div></label>
  <input type="file" id="ifc" name="ifc" accept=".ifc">
  <div class="row">
    <button class="btn" type="submit">Process</button>
    <label class="chk"><input type="checkbox" name="resolve"> Standardize odd angles (snap to trade)</label>
  </div>
</form>
{err}
"""

UPLOAD_SCRIPT = """<script>
 const d=document.getElementById('drop'),i=document.getElementById('ifc'),n=document.getElementById('fname');
 i.onchange=()=>{n.textContent=i.files[0]?i.files[0].name:'no file chosen'};
 ['dragover','dragenter'].forEach(e=>d.addEventListener(e,ev=>{ev.preventDefault();d.classList.add('hi')}));
 ['dragleave','drop'].forEach(e=>d.addEventListener(e,ev=>{ev.preventDefault();d.classList.remove('hi')}));
 d.addEventListener('drop',ev=>{i.files=ev.dataTransfer.files;n.textContent=i.files[0]?i.files[0].name:'no file chosen'});
</script>"""


@app.route("/")
def home():
    return PAGE.format(title="Conduit Pipeline",
                                  body=UPLOAD_BODY.format(err=""), script=UPLOAD_SCRIPT)


def _error(msg):
    err = f'<div class="banner warn" style="margin-top:20px">&#9888; {msg}</div>'
    return PAGE.format(title="Conduit Pipeline",
                                  body=UPLOAD_BODY.format(err=err), script=UPLOAD_SCRIPT)


@app.route("/process", methods=["POST"])
def process_upload():
    f = request.files.get("ifc")
    if not f or not f.filename:
        return _error("No file selected.")
    if not f.filename.lower().endswith(".ifc"):
        return _error("That doesn't look like an IFC file (need a <b>.ifc</b>).")
    os.makedirs(UPLOADS, exist_ok=True)
    stem = _stem(f.filename)
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    f.save(path)
    resolve = request.form.get("resolve") == "on"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            process.process_one(path, resolve_odd=resolve)
    except Exception as e:                       # malformed / unreadable IFC, etc.
        return _error(f"Couldn't process that file &mdash; {type(e).__name__}: {e}")
    if not os.path.exists(os.path.join(OUT, f"{stem}_pieces.csv")):
        return _error(f"No conduit runs found in <b>{f.filename}</b>. "
                      "Is this an electrical model? (HVAC/plumbing/structural have no conduit.)")
    return redirect(url_for("result", stem=stem, resolved=int(resolve)))


@app.route("/resolve/<stem>")
def resolve(stem):
    """Re-process the stored upload with odd angles standardized."""
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    if not os.path.exists(path):
        return _error("Original upload not found — please upload again.")
    with contextlib.redirect_stdout(io.StringIO()):
        process.process_one(path, resolve_odd=True)
    return redirect(url_for("result", stem=stem, resolved=1))


@app.route("/result/<stem>")
def result(stem):
    s = read_stats(stem)
    resolved = request.args.get("resolved") == "1"
    tiles = "".join(f'<div class="tile"><div class="n">{v}</div><div class="l">{l}</div></div>'
                    for v, l in [(s["conduits"], "conduit runs"), (s["bends"], "bends"),
                                 (s["sticks"], "sticks to bend"), (s["raw_sticks"], "raw sticks to buy"),
                                 (f'{s["total_ft"]}', "total ft"), (s["review"], "runs to review")])
    if s["review"] and not resolved:
        flags = "\n".join(s["flags"])
        banner = (f'<div class="banner warn"><b>&#9888; {s["review"]} run(s) need review</b> '
                  '(odd angles / drift). Bend as-is, or standardize the odd angles:'
                  f'<div class="row"><a class="btn" href="/resolve/{stem}">Standardize odd angles</a>'
                  f'<a class="btn g" href="/out/{stem}_health.txt" target="_blank">See the report</a></div>'
                  f'<div class="flags">{flags}</div></div>')
    else:
        note = " — odd angles standardized" if resolved else ""
        banner = f'<div class="banner ok">&#10003; All runs ready to fabricate{note}.</div>'

    def card(href, t, d, blank=True):
        tgt = ' target="_blank"' if blank else ""
        return f'<a class="card" href="{href}"{tgt}><div class="t">{t}</div><div class="d">{d}</div></a>'

    cards = "".join([
        card(f"/out/{stem}_cards.html", "Bend cards", "printable, per stick"),
        card(f"/out/{stem}_diagrams.html", "Diagrams", "run shapes, colored by stick"),
        card(f"/out/{stem}_cutlist.csv", "Cut list", "offcut-optimized cut plan"),
        card(f"/out/{stem}_pieces.csv", "Pieces", "per-stick data"),
        card(f"/out/{stem}_health.txt", "Data health", "runs to review"),
        card(f"/out/{stem}_job.json", "Machine job", "the hardest run, machine-ready"),
    ])
    body = (f'<h1>{stem}</h1><div class="sub">{s["conduit"]} &middot; fabrication package</div>'
            f'{banner}<div class="tiles">{tiles}</div>'
            f'<div class="cards">{cards}</div>'
            f'<div class="row" style="margin-top:22px">'
            f'<a class="btn" href="/download/{stem}">&#8681; Download package (.zip)</a>'
            f'<a class="btn g" href="/">Process another</a></div>')
    return PAGE.format(title=f"{stem} — package", body=body, script="")


@app.route("/out/<path:fn>")
def out_file(fn):
    return send_from_directory(OUT, fn)


@app.route("/download/<stem>")
def download(stem):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in os.listdir(OUT):
            if name.startswith(f"{stem}_"):
                z.write(os.path.join(OUT, name), name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{stem}_fabrication_package.zip")


# ── JSON API (for the Next.js front-end) ───────────────────────────────────────

@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def _job_payload(stem):
    urls = {k: f"/out/{stem}_{v}" for k, v in {
        "cards": "cards.html", "diagrams": "diagrams.html", "cutlist": "cutlist.csv",
        "pieces": "pieces.csv", "health": "health.txt", "job": "job.json"}.items()}
    urls["download"] = f"/download/{stem}"
    return {"ok": True, "stem": stem, "stats": read_stats(stem), "urls": urls}


@app.route("/api/process", methods=["POST", "OPTIONS"])
def api_process():
    if request.method == "OPTIONS":
        return ("", 204)
    f = request.files.get("ifc")
    if not f or not f.filename:
        return {"ok": False, "error": "No file selected."}, 400
    if not f.filename.lower().endswith(".ifc"):
        return {"ok": False, "error": "That doesn't look like an IFC file (need a .ifc)."}, 400
    os.makedirs(UPLOADS, exist_ok=True)
    stem = _stem(f.filename)
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    f.save(path)
    resolve = request.form.get("resolve") in ("on", "true", "1")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            process.process_one(path, resolve_odd=resolve)
    except Exception as e:
        return {"ok": False, "error": f"Couldn't process that file — {type(e).__name__}: {e}"}, 422
    if not os.path.exists(os.path.join(OUT, f"{stem}_pieces.csv")):
        return {"ok": False, "error": f"No conduit runs found in {f.filename}. "
                "Is this an electrical model? (HVAC / plumbing / structural have no conduit.)"}, 200
    return _job_payload(stem)


@app.route("/api/resolve/<stem>", methods=["POST", "OPTIONS"])
def api_resolve(stem):
    if request.method == "OPTIONS":
        return ("", 204)
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    if not os.path.exists(path):
        return {"ok": False, "error": "Original upload not found — please upload again."}, 404
    with contextlib.redirect_stdout(io.StringIO()):
        process.process_one(path, resolve_odd=True)
    payload = _job_payload(stem)
    payload["resolved"] = True
    return payload


if __name__ == "__main__":
    print("Conduit pipeline API → http://127.0.0.1:5000  (Next.js front-end in web/)")
    app.run(debug=False, port=5000)
