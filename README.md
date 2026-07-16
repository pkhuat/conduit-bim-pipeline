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

## Web app — drag & drop
A browser front door: drop an IFC, get the whole package (cards, cut list, BOM,
data-health, machine job) on a results page, downloadable as a zip. It can also
**standardize flagged odd angles** in one click.
```bash
pip install flask
python3 webapp/app.py            # → http://127.0.0.1:5000
```

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
