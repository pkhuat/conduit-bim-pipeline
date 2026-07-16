# Revit Day-1 Runbook (for when Apporto / Windows access lands)

The goal: make my own conduit model in Revit, export it to IFC, and run it
through the extractor — so I finally have real data to test against. Menu names
vary a little by Revit version, so adapt as needed.

## 1. Get into the Windows desktop
- Once ITS assigns **Apporto**: log into `apporto.com` with Colby SSO, launch the Windows workspace.
- Check whether **Revit** is already installed (Colby likely pre-installed it). If not, install it with my free Autodesk student license (`autodesk.com/education`).

## 2. Get a conduit model (pick one)
- **Easiest:** open the **`rme_basic_sample_project`** that ships with Revit — it already has electrical/conduit in it.
- **Or draw my own** (more control over the bends):
  - Systems tab → **Conduit**.
  - Draw a run with a couple of direction changes so it has real bends.
  - Two or three connected runs is plenty for testing.

## 3. Export to IFC — three ways (the key experiment)
File → Export → **IFC**. In the dialog, change the **IFC Version** (under
"Modify setup…") and export three separate files:

1. **IFC 2x3 — Coordination View**  → `conduit_2x3.ifc`
2. **IFC 4 — Reference View**        → `conduit_ref.ifc`
3. **IFC 4 — Design Transfer View**  → `conduit_dtv.ifc`

## 4. Get the files to the extractor
Two options:
- **Run the extractor inside Apporto** (cleanest — everything in one place): install Python on the Windows session, `pip install ifcopenshell`, copy the `bim/` folder over, run there.
- **Or download the `.ifc` files** from Apporto to my Mac and run the extractor where it already works.

## 5. Run and compare
For each file (on Windows it's `python`, on Mac `python3`):

```
python bim/extract_conduit.py conduit_2x3.ifc
python bim/extract_conduit.py conduit_ref.ifc
python bim/extract_conduit.py conduit_dtv.ifc
```

**What I'm looking for:**
- Which one(s) the extractor reads cleanly (finds the conduit *and* a real centerline)?
- Which gives a useless mesh (no centerline)?
- Whichever reads best = **the export setting I ask every customer to use.**

## 6. Then the real work starts
With a real *connected* run in hand, I can finally:
- build the **"group scattered segments into runs"** logic (the connectivity problem), and
- check that the derived bends actually match what I drew in Revit.

That's the moment the whole pipeline — real BIM model → bend job → machine sim —
works on real data.
