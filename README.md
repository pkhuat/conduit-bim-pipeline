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

## Tests
```bash
python3 bim/test_extract_conduit.py                  # 33 tests
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

Built with `ifcopenshell` + `numpy`.
