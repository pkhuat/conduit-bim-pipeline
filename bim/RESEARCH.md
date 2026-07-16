# BIM → bend job: research notes (Revit / IFC)

Research thread for the **future** BIM feature: get conduit data out of a Revit
model and interpret it into the `(advance, rotate, angle)` bend-job format the
machine already runs. Target authoring tool is confirmed: **Autodesk Revit**.
Scope here is *research only* — understanding the data, not building production code.

This is **PK's Step 1 (get conduit geometry)**; Josh owns Step 2 (parse + drive
the machine); Step 3 connects them.

---

## 0. Two layers you can tap (this is the key strategic choice)

The conduit data exists at two very different levels of "doneness":

| Layer | What it is | Who provides it | What you'd still have to do |
|---|---|---|---|
| **Raw BIM** | conduit geometry (centerlines, fittings) | Revit / IFC | **Solve the hard interpretation yourself** (§4) — ordering, bend-at-fitting, units, coords |
| **Spool / fabrication software** | finished **bend instructions** (angles, directions, distance between bends, cut length) | Allied BIM, Stratus, Greenlee **BendWorks**, EVOLVE | almost nothing — this output **is basically the bend-job format already** |

**The insight:** spool software has *already done* the geometry-to-bends
interpretation. Their output (angle / rotation / distance-between-bends / cut
length) maps almost 1:1 onto our `(advance, rotate, angle)` format. So tapping
that layer **skips the entire §4 interpretation problem** — *if* the contractor
uses one of these tools and *if* it exposes the data (file export or API).

- **Greenlee BendWorks** is the closest analog: it exists to output bend
  instructions for benders. Its data model = a de-facto "what good bend data
  looks like" reference, whether or not we use it directly.
- **Allied BIM has said they're interested in partnering** — which means they may
  share their data format / API, i.e. free research access to the easy path.
- Company preference: see how much we can do **ourselves** first (raw BIM),
  partnering as a last resort — but research the spool layer **in parallel**,
  because it both (a) might be far easier and (b) defines our target output.

**Update (researched): Allied BIM has NO open/public API.** Findings:
- Programmatic access to the model data runs through **Autodesk Platform
  Services (APS) / AEC Data Model API** — that's *Autodesk's* API, not Allied
  BIM's — outputting JSON/CSV that you **still interpret yourself**.
- Allied BIM's machine integration is **file export to specific equipment**
  (TigerStop, RazorGage, Autodesk Fabrication `.MAJ`), not an API. Feeding our
  bender would be a **partnership** (they add a "Tubender" export), not an
  off-the-shelf API.
- **Net: no turnkey shortcut exists** — every route still needs our own
  interpreter + last-mile translation. APS / AEC Data Model is worth filing as a
  possible *second input* (cloud JSON instead of IFC files), but it's
  Autodesk-locked and costs money, so **IFC export stays the independent default**.

---

## 1. How conduit lives in Revit

- Conduit is a first-class **Electrical** element in Revit (not generic geometry).
- Each conduit segment is **straight** and has a **location line** (its centerline),
  a **trade size** (e.g. 1/2", 3/4", 1"), and **connectors** at each end.
- **Bends are usually separate elements.** Revit has two modes:
  - *Conduit with Fittings* — elbows are inserted as **Conduit Fitting** family
    instances; each fitting carries the **bend angle** as a parameter.
  - *Conduit without Fittings* — the run bends without a separate elbow family.
  - **This with/without-fittings distinction is pivotal for us** (see §4).
- A conduit "run" is therefore typically *many* straight segments + elbow fittings,
  joined end-to-end by connectors — not one continuous curve.

## 2. Three ways to get the data out (Revit-focused)

| Method | What it is | Pros | Cons |
|---|---|---|---|
| **IFC export + IfcOpenShell** *(prototyped in `bim/`)* | Revit exports a file; we read it in Python | Vendor-neutral, free, fits a portable machine | Snapshot; export *settings* decide if we get a centerline (see §3) |
| **Revit API / Dynamo** | Code/visual script *inside* Revit reads `Conduit` elements directly | Richest, most accurate (location curve, size, connectors, fitting angles) | Revit-only; needs the app + dev (Dynamo is the low-code on-ramp) |
| **Autodesk Platform Services (APS)** | Autodesk cloud REST API | Programmatic, no local Revit at query time | Autodesk-locked, cost; geometry is **tessellated** there too, so centerline is lost like Reference View |

**Take:** start with IFC export (vendor-neutral, runs on a Mac, no Revit at read
time). The **Revit API is the higher-fidelity alternative** — it hands you the
**connectivity (via element connectors) and fitting bend angles directly**, i.e.
the two hardest parts of the IFC path, for free (Revit's model already has
conduit as clean `Conduit` elements + `Conduit Fitting` elbows with angle
parameters). Trade-off: it's **Revit-locked** and must run *inside* Revit
(Windows). **pyRevit / Dynamo is the Python on-ramp** — far lower barrier than a
full C#/.NET add-in. Worth a small pyRevit experiment once Revit access lands, to
decide if it should be the *primary* path for Revit customers with IFC as the
universal fallback. (Note: using the API just to *export IFC* is only automating
the file export — the real win is reading conduit elements **directly**, no file.)

## 3. How conduit maps to IFC (and why geometry varies)

- Revit **Conduit → `IfcCableCarrierSegment`** (PredefinedType `CONDUITSEGMENT`).
- Revit **Conduit Fitting → `IfcCableCarrierFitting`** (the elbows).
- Trade size comes through as a **property** (nominal / outer diameter) in a Pset.
- Geometry depends on the **export setting (MVD + IFC version)** — this explains
  what we already saw with the buildingSMART files:

| Export choice | Geometry you get | Usable centerline? |
|---|---|---|
| IFC2x3 Coordination View | swept solids / curves (older, very common) | often yes |
| IFC4 **Reference View** | **tessellated mesh** | ❌ no (this is what bit us) |
| IFC4 **Design Transfer View** | parametric, richer | ✅ most likely |

→ "Getting the data" is not just "send the IFC" — it's *"export conduit, with the
centerline (Axis) preserved."* The export setting is part of the research answer.

### Empirical: conduit geometry shows up in 3 forms (tested real files)

| Source file | Geometry stored as | Extractor result |
|---|---|---|
| our generated `sample_conduit.ifc` | **Axis** polyline (centerline) | ✅ derives bends |
| buildingSMART `Building-Hvac.ifc` | **Tessellation** (mesh) | ❌ no centerline |
| IfcOpenShell `435--cableCarrier--abort.ifc` | **SweptDiskSolid** (directrix curve) | ✅ now reads centerline (extractor extended) |

The extractor now handles all three geometry forms (`Axis` polyline,
`IfcSweptDiskSolid` directrix, `IfcExtrudedAreaSolid` axis) with world-coordinate
placement transforms, reports the file's length unit (mm / m / FOOT — Revit uses
feet), and reads **both IFC4 and IFC2x3**. (IFC2x3 — Revit's most common export —
has no `IfcCableCarrierSegment` occurrence class; conduit is a generic
`IfcFlowSegment` typed by `IfcCableCarrierSegmentType`, so we gather occurrences
by type too via `IfcRelDefinesByType`.)

### Real IFC2x3 Revit file (`project1.ifc`) — what it taught us
A real Revit IFC2x3 export with two `ExtrudedAreaSolid` cable-tray segments. The
tool reads them fine now, but the derived job was **garbage**: two 100mm pieces
~16m apart in the building got stitched into a fake 16,000mm "advance" with
invented 90° bends. **Lesson: the segments are NOT a connected run** — naive
"stitch in order" is wrong. The real interpretation step is **grouping scattered
segments into actual runs, then deriving bends per run.**

**Now fixed.** `group_into_runs()` rebuilds runs by matching shared endpoints, so
project1 correctly reports **two separate 100mm pieces (no fake bend)**. Built and
tested against a scattered/shuffled synthetic model (`make_scattered_ifc.py`): it
regroups two runs and derives the right bends (one 90°, two 45°) regardless of
the order the segments appear. Port-based grouping (`IfcRelConnectsPorts`) is a
future robustness upgrade for messy exports.

Lessons / still TODO: (1) Most *public* conduit `.ifc` files are tiny
single-element tests — real multi-bend runs are rare publicly, so the company's
own export remains the real target. (2) ✅ **Connectivity/ordering DONE**
— `group_into_runs` rebuilds runs from shared endpoints (port-based grouping is a
future robustness upgrade). (3) ✅ **Polyline simplification DONE** —
Ramer-Douglas-Peucker (`simplify_polyline`) collapses noise and dense curve
points into clean corners before deriving bends (true arc-radius detection is a
later refinement). (4) ✅ **Unit normalization DONE** —
all geometry converted to mm via `calculate_unit_scale`, so a metres/feet file
comes out in mm and the grouping/simplify tolerances stay correct. (5) ✅
**Fitting-based bends DONE (first pass)** — fittings are folded into run-grouping
so a `segment → fitting → segment` chain stitches into one run and the elbow bend
comes through geometrically (`make_fitting_ifc.py` proves it: segments-only = 2
runs, +fittings = 1 run with a 90° bend). Real-data refinements: read a fitting's
explicit Angle property (vs derive it), and port-based grouping.

### ★ Revit 2027 MVD experiment — DONE on real data (2026-06-24)
Drew a real conduit run in **Revit 2027** (on a Shadow PC cloud Windows desktop)
and exported it three ways. Both research questions now have empirical answers:

| Export setup | Conduit geometry | Centerline usable? |
|---|---|---|
| IFC2x3 Coordination View 2.0 | `ExtrudedAreaSolid` | ✅ yes |
| IFC4 Reference View [BuildingService] | `ExtrudedAreaSolid` | ✅ yes |
| IFC4 Design Transfer View [Unofficial] | `ExtrudedAreaSolid` | ✅ yes |

**Finding 1 (MVD): all three kept a usable centerline — even Reference View.**
This *contradicts* the §3 prediction that Reference View tessellates to a useless
mesh. For **conduit** in Revit 2027 the centerline survives every setting (the Ref
file is bigger — other elements tessellate — but the conduit itself stays an
extruded solid). So the "which export setting?" ask is *less* fragile than feared;
**IFC4 Design Transfer View** is still the safest recommendation, and this should
be re-checked on a bigger real model.

**Finding 2 (connectivity): real "conduit without fittings" doesn't share
endpoints.** Each straight is **trimmed back by the bend radius**, leaving a
~456 mm gap (the elbow) between consecutive segments, and the **elbow exports as
an unreadable `MappedRepresentation`**. So pure shared-endpoint matching found
**0 bends**. But Revit *does* export **connection ports** —
`IfcDistributionPort`s wired by `IfcRelConnectsPorts` (attached via
`IfcRelConnectsPortToElement` in IFC2x3 / `IfcRelNests` in IFC4) — giving the true
`segment → elbow → segment` chain. **Port-based grouping is now built**
(`port_based_runs`): order the segments by ports, put each bend vertex at the
**intersection (PI) of the two adjacent straights**, and take the angle from their
direction change — so the unreadable elbow geometry is never needed. All three
exports now yield the **same two 90° bends** that were drawn, and the derived job
runs clean through the simulator. **This is the first full real-BIM → bend-job →
machine-sim validation.** (`group_into_runs` stays as the fallback for files
without ports.)

## 4. The interpretation problem (the hard, interesting part)

Given the geometry, deriving `(advance, rotate, angle)` requires solving:

1. **Centerline** — read each segment's `Axis` polyline (or the Revit location curve).
2. **Ordering / connectivity** — runs arrive as many disconnected pieces; order
   them by walking connectors (`IfcRelConnectsPorts`) or shared endpoints. *Our
   PoC assumed they were already in order — real data won't be.*
3. **Where the bend is** — if bends are **fittings**, the bend angle is the
   fitting's parameter (and the segments either side are straight). If there are
   no fitting elements, the bend is the kink between two segment directions. We
   must handle both.
4. **Roll / rotate** — the change of bend *plane* between consecutive bends
   (our PoC derives this from consecutive plane normals; springback is still TODO).
5. **Units & coordinates** — Revit works internally in **feet**; IFC export is
   usually mm. Models can carry large **survey/shared-coordinate** offsets that
   must be normalized.
6. **Machine constraints** — trade size → our die/bend radius; minimum straight
   length between bends; max bend angle. The geometry is "ideal"; the machine isn't.

## 5. Open questions for the company

- Will exports be *conduit with fittings* or *without*? (Changes §4.3 entirely.)
- Which export setting can they commit to? (Aim: IFC4 + Design Transfer View, or
  IFC2x3 Coordination View — both tend to keep a centerline.)
- Can they send **one real conduit export now** to test against?
- What trade sizes / bend radii does the machine support (to map size → die)?

## 6. Prioritized research plan

1. **Get Revit + a model.** Students/interns can get a **free Revit education
   license** from Autodesk. Load the **`rme_basic_sample_project`** (ships with
   electrical/conduit) as a no-cost test model.
2. **★ Key experiment — the MVD diff.** Export the *same* conduit run three ways
   (IFC2x3 Coordination View, IFC4 Reference View, IFC4 Design Transfer View) and
   compare what `bim/extract_conduit.py` finds. This empirically answers "what
   export setting do we ask customers for." (Tests the §3 table for real.)
3. **Resolve the fittings question** — inspect whether bends are
   `IfcCableCarrierFitting` elements or centerline kinks. Search:
   *"Revit conduit fitting IFC IfcCableCarrierFitting elbow angle."*
4. **Try Dynamo** — a no-code graph that lists all conduit + geometry is a fast
   way to see the data without writing an add-in.
5. **Read the schema** — buildingSMART definitions for `IfcCableCarrierSegment`
   and `IfcCableCarrierFitting`.

## 7. Resources

- buildingSMART IFC schema (search the entity names above on `ifc43-docs` / standards site)
- IfcOpenShell docs — `docs.ifcopenshell.org`
- Autodesk Revit API — `Autodesk.Revit.DB.Electrical` namespace (`Conduit`, `ConduitType`)
- Autodesk Platform Services — `aps.autodesk.com`
- Free Revit education license — `autodesk.com/education`
- GitHub code search for real test files: `IfcCableCarrierSegment extension:ifc`
