# bim/ — IFC → bend job (proof of concept)

Roadmap step 5: read conduit out of a BIM/IFC export and turn its centerline
into the `(advance, rotate, angle)` bend-job format the rest of the system
already speaks. This is the BIM-side counterpart to `SimMachine` — it lets us
build and demo the whole pipeline now, using a generated sample file instead of
waiting on a real export.

## Run the whole pipeline

```bash
python3 bim/make_sample_ifc.py            # 1. write bim/sample_conduit.ifc
python3 bim/extract_conduit.py            # 2. read it -> bim/derived_job.json
python3 run_demo.py bim/derived_job.json  # 3. run the derived job in the sim
```

Point the extractor at a real export when you get one:

```bash
python3 bim/extract_conduit.py path/to/real_export.ifc
```

## Tests

```bash
python3 bim/test_extract_conduit.py        # no pytest required
```

Locks in connectivity, simplification, unit normalization, fitting-aware
grouping, and IFC2x3 handling against the synthetic fixtures (plus the
downloaded real files when present).

## Files

| File | Purpose |
|---|---|
| `make_sample_ifc.py` | Generates a sample IFC: one conduit run (an offset) made of `IfcCableCarrierSegment` pieces, each with an `Axis` centerline. Stand-in input. |
| `extract_conduit.py` | Finds the conduit, stitches the centerline, derives `(advance, rotate, angle)` bends, writes a bend job, and prints its assumptions. |
| `sample_conduit.ifc` | Generated sample (step 1 output). |
| `derived_job.json` | Generated bend job (step 2 output) — runnable by `run_demo.py`. |
| `make_scattered_ifc.py` | Generates a shuffled, multi-run model — fixture for run-grouping. |
| `make_fitting_ifc.py` | Generates a segment→fitting→segment model — fixture for fitting-aware grouping. |
| `test_extract_conduit.py` | Test suite (plain `python3`, or pytest). |
| `RESEARCH.md` | Research notes: Revit/IFC, geometry forms, build-vs-partner decisions. |

## Known simplifications (not production)

- `rotate` is derived from the bend-plane change only; springback and full roll
  handling are TODO.
- Output is normalized geometry (mm / degrees), **not** calibrated motor units
  (degrees/mm → motor steps is still TODO, with the team).
- Validated on real Revit exports so far only for **planar 90° bends**; 3D bends
  (offset/saddle, non-90°, out-of-plane roll) still need real-data testing.
- Reading a fitting's explicit Angle property (vs deriving it from geometry) is a
  future refinement.

Connectivity now prefers Revit's **IFC connection ports** (`IfcRelConnectsPorts`),
falling back to shared-endpoint matching for files without ports — validated on a
real Revit conduit export (see `RESEARCH.md`, "Revit 2027 MVD experiment").

Needs `ifcopenshell` (`pip3 install ifcopenshell`, already in `requirements.txt`).
