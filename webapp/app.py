"""Web front door for the conduit pipeline.

Drag-drop a Revit/BIM IFC export in the browser and get back the full
fabrication package — bend cards, diagrams, cut list, bill of materials, a
data-health report, and a machine job — rendered on a results page and
downloadable as a zip. Wraps the same `bim/process.py` the CLI runs.

    pip install flask
    python3 webapp/app.py        # then open http://127.0.0.1:5050

Simulation/office tool only; produces the machine-ready job, does not drive hardware.
"""

import csv
import io
import json
import logging
import os
import re
import sys
import time
import uuid
import zipfile
import contextlib

from flask import (Flask, request, redirect, url_for, send_file,
                   send_from_directory, abort)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIM = os.path.join(ROOT, "bim")
# CONDUIT_OUT_DIR is shared with the pipeline (process.py) so both read/write the
# same place — set it to a writable volume in production.
OUT = os.environ.get("CONDUIT_OUT_DIR") or os.path.join(BIM, "out")
UPLOADS = os.environ.get("CONDUIT_UPLOAD_DIR") or os.path.join(HERE, "uploads")
sys.path.insert(0, BIM)
import process  # noqa: E402  (the pipeline)

sys.path.insert(0, ROOT)
try:
    import run_stick_job as _driver              # bend_one / run_stick choreography
    from machine.sim_machine import SimMachine   # safe: opens no serial port, nothing moves
    _SIM_OK = True
except Exception:                                # machine/ not present -> machine view disabled
    _SIM_OK = False

# --- configuration (env-overridable for production) ---------------------------
PORT = int(os.environ.get("PORT", "5050"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "250"))
# comma-separated allowed CORS origins; "*" (default) allows any — set to the
# front-end's URL in production, e.g. ALLOWED_ORIGINS=https://app.example.com
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("conduit.api")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

_STEM_RE = re.compile(r"[A-Za-z0-9_.-]+")


def _stem(filename):
    """A safe base stem from an uploaded filename (no job id yet)."""
    base = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"[^A-Za-z0-9_.-]", "_", base) or "upload"


def _new_job_stem(filename):
    """A unique per-upload stem, so concurrent or same-named uploads never collide
    or overwrite one another in the shared output directory."""
    return f"{_stem(filename)}-{uuid.uuid4().hex[:8]}"


def _valid_stem(stem):
    """Guard stems taken from the URL against path tricks / unknown jobs."""
    return bool(stem) and re.fullmatch(_STEM_RE, stem) is not None


def _display_name(stem):
    """The human name for a job stem (drops the -<8hex> job-id suffix)."""
    return re.sub(r"-[0-9a-f]{8}$", "", stem)


JOB_TTL_HOURS = int(os.environ.get("JOB_TTL_HOURS", "24"))


def _cleanup_old_jobs():
    """Best-effort: delete job artifacts older than JOB_TTL_HOURS so the shared
    output/upload dirs don't grow without bound in a long-running service. The
    shared landing page and aggregate index are preserved."""
    if JOB_TTL_HOURS <= 0:
        return
    cutoff = time.time() - JOB_TTL_HOURS * 3600
    for d in (OUT, UPLOADS):
        try:
            for fn in os.listdir(d):
                if fn in ("index.html", "all_jobs.json"):
                    continue
                p = os.path.join(d, fn)
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
        except OSError:
            pass


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


@app.route("/health")
def health():
    """Liveness/readiness probe for load balancers and container orchestration."""
    return {"ok": True, "service": "conduit-pipeline-api"}


@app.errorhandler(413)
def _too_large(_e):
    msg = f"File too large — the limit is {MAX_UPLOAD_MB} MB."
    if request.path.startswith("/api/"):
        return {"ok": False, "error": msg}, 413
    return _error(msg), 413


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
    _cleanup_old_jobs()
    stem = _new_job_stem(f.filename)
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    f.save(path)
    resolve = request.form.get("resolve") == "on"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            status = process.process_one(path, resolve_odd=resolve)
    except Exception as e:                       # malformed / unreadable IFC, etc.
        log.exception("process failed for %s", f.filename)
        return _error(f"Couldn't process that file &mdash; {type(e).__name__}: {e}")
    if not os.path.exists(os.path.join(OUT, f"{stem}_pieces.csv")):
        reason = status.get("reason") if isinstance(status, dict) else None
        return _error(reason or f"No conduit runs found in <b>{f.filename}</b>. "
                      "Is this an electrical model? (HVAC/plumbing/structural have no conduit.)")
    return redirect(url_for("result", stem=stem, resolved=int(resolve)))


@app.route("/resolve/<stem>")
def resolve(stem):
    """Re-process the stored upload with odd angles standardized."""
    if not _valid_stem(stem):
        abort(404)
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    if not os.path.exists(path):
        return _error("Original upload not found — please upload again.")
    with contextlib.redirect_stdout(io.StringIO()):
        process.process_one(path, resolve_odd=True)
    return redirect(url_for("result", stem=stem, resolved=1))


@app.route("/result/<stem>")
def result(stem):
    if not _valid_stem(stem):
        abort(404)
    s = read_stats(stem)
    name = _display_name(stem)
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
    body = (f'<h1>{name}</h1><div class="sub">{s["conduit"]} &middot; fabrication package</div>'
            f'{banner}<div class="tiles">{tiles}</div>'
            f'<div class="cards">{cards}</div>'
            f'<div class="row" style="margin-top:22px">'
            f'<a class="btn" href="/download/{stem}">&#8681; Download package (.zip)</a>'
            f'<a class="btn g" href="/">Process another</a></div>')
    return PAGE.format(title=f"{name} — package", body=body, script="")


@app.route("/out/<path:fn>")
def out_file(fn):
    return send_from_directory(OUT, fn)


@app.route("/download/<stem>")
def download(stem):
    if not _valid_stem(stem):
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in os.listdir(OUT):
            if fn.startswith(f"{stem}_"):
                z.write(os.path.join(OUT, fn), fn)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{_display_name(stem)}_fabrication_package.zip")


# ── JSON API (for the Next.js front-end) ───────────────────────────────────────

@app.after_request
def _cors(resp):
    origin = request.headers.get("Origin")
    if "*" in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def _job_payload(stem):
    urls = {k: f"/out/{stem}_{v}" for k, v in {
        "cards": "cards.html", "diagrams": "diagrams.html", "cutlist": "cutlist.csv",
        "pieces": "pieces.csv", "health": "health.txt", "job": "job.json"}.items()}
    urls["download"] = f"/download/{stem}"
    return {"ok": True, "stem": stem, "name": _display_name(stem),
            "stats": read_stats(stem), "urls": urls}


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
    _cleanup_old_jobs()
    stem = _new_job_stem(f.filename)
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    f.save(path)
    resolve = request.form.get("resolve") in ("on", "true", "1")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            status = process.process_one(path, resolve_odd=resolve)
    except Exception as e:
        log.exception("api process failed for %s", f.filename)
        return {"ok": False, "error": f"Couldn't process that file — {type(e).__name__}: {e}"}, 422
    if not os.path.exists(os.path.join(OUT, f"{stem}_pieces.csv")):
        reason = status.get("reason") if isinstance(status, dict) else None
        return {"ok": False, "error": reason or
                f"No conduit runs found in {f.filename}. Is this an electrical model? "
                "(HVAC / plumbing / structural have no conduit.)"}, 200
    return _job_payload(stem)


def _load_runs(stem):
    """The structured per-run data (bim/out/<stem>_runs.json), or None."""
    try:
        with open(os.path.join(OUT, f"{stem}_runs.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@app.route("/api/jobs")
def api_jobs():
    """Every processed job (a building), newest first — for the jobs list."""
    jobs = []
    try:
        for fn in os.listdir(OUT):
            if not fn.endswith("_runs.json"):
                continue
            stem = fn[:-len("_runs.json")]
            s = read_stats(stem)
            jobs.append({"stem": stem, "name": _display_name(stem),
                         "conduit": s["conduit"], "conduits": s["conduits"],
                         "bends": s["bends"], "review": s["review"],
                         "mtime": os.path.getmtime(os.path.join(OUT, fn))})
    except OSError:
        pass
    jobs.sort(key=lambda j: j["mtime"], reverse=True)
    return {"ok": True, "jobs": jobs}


@app.route("/api/jobs/<stem>")
def api_job(stem):
    """One job: summary stats + output URLs + every run (for navigation)."""
    if not _valid_stem(stem):
        return {"ok": False, "error": "Bad job id."}, 404
    rj = _load_runs(stem)
    if rj is None:
        return {"ok": False, "error": "Job not found."}, 404
    payload = _job_payload(stem)
    payload["runs"] = rj["runs"]
    payload["sim"] = _SIM_OK
    return payload


@app.route("/api/jobs/<stem>/machine", methods=["POST", "OPTIONS"])
def api_machine(stem):
    """Drive the conduit through the machine SIMULATOR and return the real
    ClearCore command log. Simulation only — opens no serial port, moves nothing."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not _valid_stem(stem):
        return {"ok": False, "error": "Bad job id."}, 404
    if not _SIM_OK:
        return {"ok": False, "error": "Machine simulator unavailable on this server."}, 503
    rj = _load_runs(stem)
    if rj is None:
        return {"ok": False, "error": "Job not found."}, 404

    body = request.get_json(silent=True) or {}
    all_runs = rj["runs"]
    if isinstance(body.get("runs"), list) and body["runs"]:
        try:
            want = {int(x) for x in body["runs"]}
        except (TypeError, ValueError):
            return {"ok": False, "error": "Bad run list."}, 400
        runs = [r for r in all_runs if r["run"] in want]
        which = sorted(want)
        if not runs:
            return {"ok": False, "error": "No matching runs."}, 404
    else:
        which = body.get("run", "all")
        runs = all_runs
        if which != "all":
            try:
                which = int(which)
            except (TypeError, ValueError):
                return {"ok": False, "error": "Bad run number."}, 400
            runs = [r for r in all_runs if r["run"] == which]
            if not runs:
                return {"ok": False, "error": f"Run {which} not found."}, 404

    machine = SimMachine(verbose=False)
    sticks = []
    for r in runs:
        for p in r.get("pieces", []):
            if not p.get("bends"):
                continue
            _driver.run_stick(machine, p["bends"],
                              f"run {r['run']} stick {p['piece']}", verbose=False)
            sticks.append({"run": r["run"], "piece": p["piece"], "bends": len(p["bends"])})

    CAP = 6000  # keep the payload sane if a whole building is driven
    hist = machine.history
    commands = [{"board": b, "cmd": c, "response": resp} for (b, c, resp) in hist[:CAP]]
    final = {name: {"position": round(ax["position"], 2), "enabled": ax["enabled"]}
             for name, ax in machine.axes.items()}
    return {"ok": True, "stem": stem, "run": which, "sticks": sticks,
            "commands": commands, "truncated": len(hist) > CAP,
            "warnings": machine.warnings, "final_state": final,
            "counts": {"commands": len(hist), "warnings": len(machine.warnings),
                       "sticks": len(sticks)}}


@app.route("/api/machine/manual", methods=["POST", "OPTIONS"])
def api_machine_manual():
    """Drive the SIMULATOR from a hand-built bend program (no BIM model) — the
    'create a bend from scratch' bender. Body: {bends: [{angle, roll, distance}]},
    1–4 bends, angle 0–90°, distance in inches (feed before that bend)."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not _SIM_OK:
        return {"ok": False, "error": "Machine simulator unavailable on this server."}, 503
    body = request.get_json(silent=True) or {}
    raw = body.get("bends")
    if not isinstance(raw, list) or not (1 <= len(raw) <= 4):
        return {"ok": False, "error": "Provide 1 to 4 bends."}, 400
    bends = []
    for b in raw:
        try:
            angle = float(b.get("angle"))
            roll = float(b.get("roll") or 0)
            dist_in = float(b.get("distance") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Each bend needs a numeric angle."}, 400
        if not (0 <= angle <= 90):
            return {"ok": False, "error": "Each bend angle must be between 0 and 90°."}, 400
        bends.append({"advance": round(dist_in * 25.4, 1), "angle": angle,
                      "rotate": abs(roll), "roll_dir": 1 if roll > 0 else -1 if roll < 0 else 0})
    machine = SimMachine(verbose=False)
    _driver.run_stick(machine, bends, "manual bend program", verbose=False)
    commands = [{"board": bd, "cmd": c, "response": r} for (bd, c, r) in machine.history]
    final = {n: {"position": round(ax["position"], 2), "enabled": ax["enabled"]}
             for n, ax in machine.axes.items()}
    return {"ok": True, "run": "manual", "sticks": [{"run": 0, "piece": 1, "bends": len(bends)}],
            "commands": commands, "truncated": False, "warnings": machine.warnings,
            "final_state": final,
            "counts": {"commands": len(machine.history), "warnings": len(machine.warnings), "sticks": 1}}


def _overrides_path(stem):
    return os.path.join(UPLOADS, f"{stem}.overrides.json")   # lives outside OUT's cleanup


def _load_overrides(stem):
    try:
        with open(_overrides_path(stem)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _reprocess_with_overrides(stem, ov):
    """Persist the per-run overrides and re-run the pipeline applying them (snap odd
    angles on the listed runs; supply an OD for runs whose size was set). Returns the
    updated job payload, or an (error, status) tuple."""
    src = os.path.join(UPLOADS, f"{stem}.ifc")
    if not os.path.exists(src):
        return {"ok": False, "error": "Original upload not found — please upload again."}, 404
    size = {int(k): float(v) for k, v in (ov.get("size") or {}).items()}
    try:
        with open(_overrides_path(stem), "w") as fh:
            json.dump(ov, fh)
        with contextlib.redirect_stdout(io.StringIO()):
            process.process_one(src, resolve_runs=set(ov.get("snap", [])), size_overrides=size)
    except Exception as e:
        log.exception("reprocess failed for %s", stem)
        return {"ok": False, "error": f"Couldn't re-process — {type(e).__name__}: {e}"}, 422
    rj = _load_runs(stem)
    payload = _job_payload(stem)
    payload["runs"] = rj["runs"] if rj else []
    payload["sim"] = _SIM_OK
    return payload


@app.route("/api/trade-sizes")
def api_trade_sizes():
    """Standard conduit trade sizes (label + representative OD) for the size picker."""
    return {"ok": True, "sizes": process.br.ec.trade_sizes()}


@app.route("/api/jobs/<stem>/resolve-run", methods=["POST", "OPTIONS"])
def api_resolve_run(stem):
    """Standardize the odd angles of ONE run (accumulates across calls) and re-process."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not _valid_stem(stem):
        return {"ok": False, "error": "Bad job id."}, 404
    body = request.get_json(silent=True) or {}
    try:
        run_no = int(body.get("run"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Bad run number."}, 400
    ov = _load_overrides(stem)
    ov["snap"] = sorted(set(ov.get("snap", [])) | {run_no})
    return _reprocess_with_overrides(stem, ov)


@app.route("/api/jobs/<stem>/set-size", methods=["POST", "OPTIONS"])
def api_set_size(stem):
    """Set the conduit OD (mm) for ONE run whose size couldn't be read, then re-process
    so take-up correction and a die apply to it."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not _valid_stem(stem):
        return {"ok": False, "error": "Bad job id."}, 404
    body = request.get_json(silent=True) or {}
    try:
        run_no = int(body.get("run"))
        od_mm = float(body.get("od_mm"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Need a run number and a conduit OD."}, 400
    ov = _load_overrides(stem)
    ov.setdefault("size", {})[str(run_no)] = od_mm
    return _reprocess_with_overrides(stem, ov)


@app.route("/api/resolve/<stem>", methods=["POST", "OPTIONS"])
def api_resolve(stem):
    if request.method == "OPTIONS":
        return ("", 204)
    if not _valid_stem(stem):
        return {"ok": False, "error": "Bad job id."}, 404
    path = os.path.join(UPLOADS, f"{stem}.ifc")
    if not os.path.exists(path):
        return {"ok": False, "error": "Original upload not found — please upload again."}, 404
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            process.process_one(path, resolve_odd=True)
    except Exception as e:
        log.exception("api resolve failed for %s", stem)
        return {"ok": False, "error": f"Couldn't re-process — {type(e).__name__}: {e}"}, 422
    payload = _job_payload(stem)
    payload["resolved"] = True
    return payload


if __name__ == "__main__":
    # Dev only. In production run under gunicorn (see README / Dockerfile.api):
    #   gunicorn -w 2 -t 120 -b 0.0.0.0:$PORT webapp.app:app
    print(f"Conduit pipeline API (dev server) → http://127.0.0.1:{PORT}")
    app.run(debug=False, host="127.0.0.1", port=PORT)
