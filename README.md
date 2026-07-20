# Conduit BIM → Fabrication Pipeline

Turn a building's **BIM/IFC model** (e.g. a Revit electrical export) into organized,
**fabrication-ready conduit bend instructions** — the recipe an electrician or a CNC
bender follows to build every conduit run in the building.

## What it does
- **Extracts** every conduit run from an IFC model (port-based run reconstruction).
- **Derives** each bend — feed length, angle, and roll direction.
- **Cleans** to trade-standard angles (90 / 45 / 30 / 22.5 …), honestly flagging genuinely odd ones.
- **Cuts** each run into 10-ft sticks, with couplers only on straight sections.
- **Corrects** feeds for bend-shoe take-up (Mike Holt round-raceway method).
- **Recognizes** trade operations — offsets and 3-point saddles, with rise / shrink / multiplier.
- **Optimizes** material — bin-packs offcuts to cut how many raw sticks you buy.
- **Outputs** printable per-stick bend cards, 3D diagrams, CSV spreadsheets, a bill of
  materials, a machine-readable job, and a per-run data-health report.
- **Validates** by rebuilding each run from its own recipe and comparing to the model
  (median deviation ≈ 0 mm).

## Quick start
```bash
pip install -r requirements.txt
python3 bim/process.py bim/samples/sample_elec.ifc   # a full Revit sample building
open bim/out/index.html                              # cards, diagrams, BOM, health
```

Or the smaller hand-built check case:
```bash
python3 bim/process.py bim/samples/conduit_dtv.ifc
```

## Web app (Next.js + API)
A modern front end — **Next.js / React / TypeScript** (`web/`) — talking to the
pipeline exposed as a JSON API (`webapp/app.py`). Drop an IFC → a dashboard with the
whole package (cards, cut list, BOM, data-health, machine job) → download the zip.
One click **standardizes flagged odd angles**.

### Development (dev servers, hot reload)
**One command** — starts both the API and the front end, stops both on Ctrl-C:
```bash
./run.sh                                  # → open http://localhost:3000
```
<details><summary>…or run the two pieces by hand (two terminals)</summary>

```bash
# 1) the pipeline API (Python — ifcopenshell/numpy live here)
pip install flask
python3 webapp/app.py                    # → http://127.0.0.1:5050

# 2) the Next.js front end (Node)
cd web && npm install && npm run dev      # → http://localhost:3000
```
</details>

### Production
The whole product runs in production mode with **one command** (gunicorn-served API +
built Next.js front end, in containers):
```bash
cp .env.example .env        # then edit for your URLs
docker compose up --build   # → open http://localhost:3000
```

What "production" means here (vs. the dev servers):
- **API** runs under **gunicorn** (multi-worker), not Flask's dev server.
- **Front end** is a real `next build` + `next start`, not `next dev`.
- **Per-job isolation** — every upload gets a unique job id, so concurrent or
  same-named uploads never collide in the shared output store.
- **Hardened**: upload size cap (`MAX_UPLOAD_MB`, 413 on exceed), strict `.ifc`
  check, CORS locked to `ALLOWED_ORIGINS`, `/health` probe, request logging,
  stem validation, and TTL cleanup of old jobs (`JOB_TTL_HOURS`).
- **Config via env** — `PORT`, `MAX_UPLOAD_MB`, `ALLOWED_ORIGINS`,
  `NEXT_PUBLIC_API_URL`, `CONDUIT_OUT_DIR`, `JOB_TTL_HOURS` (see `.env.example`).

Run the API alone under gunicorn (no Docker):
```bash
pip install -r requirements.txt
gunicorn -w 2 -t 120 -b 0.0.0.0:5050 webapp.app:app
```

### Deploy: Vercel (front end) + Render (API)
The Python API can't run on Vercel (native `ifcopenshell`, long parses), so the API
goes to Render and the Next.js app to Vercel. Both are free-tier friendly. Deploy the
API first so you have its URL for the front end.

**1 — API on Render** (`render.yaml` is a ready blueprint)
- Render → **New + → Blueprint** → pick this repo. It builds `webapp/Dockerfile`.
- Copy the live URL, e.g. `https://conduit-api.onrender.com`. Check `…/health`.

**2 — Front end on Vercel**
- Vercel → **Add New → Project** → import this repo.
- Set **Root Directory = `web`** (Vercel auto-detects Next.js there).
- Add env var **`NEXT_PUBLIC_API_URL`** = the Render URL (must be **https**).
- Deploy; note the app URL, e.g. `https://conduit.vercel.app`.

**3 — Lock CORS**
- Back on Render, set **`ALLOWED_ORIGINS`** = the Vercel URL, and redeploy.

`/health` is the readiness probe. (Render's free tier cold-starts after idle — first
request may take ~30–60 s.)

## Machine handoff
The pipeline stops at a validated, machine-ready **`job.json`** (feeds in mm, angles
in degrees, take-up corrected) plus the ClearCore command protocol in
`machine/commands.py`. That's the seam to the Pi/firmware — see
[docs/MACHINE_INTERFACE.md](docs/MACHINE_INTERFACE.md) for the schema, the command
vocabulary, and how calibration/springback plug in.

## Drive the (simulated) machine
The machine job runs end to end through a software model of the firmware — no
hardware, nothing moves:
```bash
python3 demo.py bim/samples/conduit_dtv.ifc   # IFC -> recipe -> bent in the simulator
python3 run_stick_job.py --run 1              # drive any run through the sim
python3 run_stick_job.py --all                # drive the whole building
```
`machine/commands.py` defines the ClearCore command interface (the firmware's own
grammar); `SimMachine` implements it as a firmware model, so the full BIM → recipe →
machine path is exercised in software. Driving **real** hardware uses the same
command interface with a serial-backed transport (kept in the machine's own repo).

## Tests
```bash
python3 bim/test_extract_conduit.py    # 33 engine tests
python3 test_sim_machine.py            # 3 simulator/driver tests
```

## Layout
| File | Role |
|---|---|
| `bim/extract_conduit.py` | IFC parsing, bend derivation, stick-cutting, take-up, trade ops |
| `bim/bend_report.py` | schedule, CSVs, bill of materials (with offcut optimization) |
| `bim/bend_card.py` / `bim/bend_diagram.py` | printable bend cards / 3D diagrams |
| `bim/validate.py` | round-trip geometry validation |
| `bim/qa.py` | per-run data-health report |
| `bim/calibration.py` | units → motor-steps + springback scaffold |
| `bim/process.py` | one command that produces every output |
| `machine/commands.py` | ClearCore command interface (protocol vocabulary) |
| `machine/sim_machine.py` | software model of the firmware (drives with no hardware) |
| `run_stick_job.py` / `demo.py` | drive a run / the whole arc through the simulator |

Built with `ifcopenshell` + `numpy` (no other runtime deps).
