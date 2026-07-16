# Demo walkthrough — BIM → organized bend data

A read-aloud script. The point of this demo is the **organized, per-conduit bend
data** — the same kind of fabrication output Allied BIM produces. Lead with *how
we process the data* and *the readable output*, not the internals.

---

## Before the call (2 min)
```bash
python3 bim/process.py bim/samples/sample_elec.ifc   # makes EVERYTHING -> bim/out/
open bim/out/index.html                               # landing page: all jobs + links
```
- Everything lives in **`bim/out/`** now (CSVs, diagrams, machine job, and an
  `index.html` that links them). One command refreshes it.
- Zoom VS Code in with **Cmd + =** so the terminal reads on screen.
- Have `bim/out/index.html` open in a browser tab.

---

## 0 — Frame it: "how we process the data" (say this first, ~45 sec)

> **Say:** "What we're building is the same idea as Allied BIM — take a BIM model
> and turn it into organized, fabrication-ready bend data. Here's how our pipeline
> processes the data, in seven steps:
> 1. **Read the BIM model** — we pull every conduit out of the Revit export.
> 2. **Rebuild the runs** — conduit comes as lots of separate straight pieces with
>    elbows; we use Revit's own connection data to stitch each set back into one
>    complete conduit run.
> 3. **Walk each run** — we measure its total length and find every bend.
> 4. **Record each bend** — the three numbers you'd fabricate from: how far you
>    feed before the bend, the bend angle, and which way it rolls.
> 5. **Clean to trade standards** — snap to the standard electrician angles
>    (90/45/30/22.5) and drop tiny noise.
> 6. **Cut to 10-ft sticks & correct the marks** — split each run into ≤10 ft
>    sticks with couplers only in straights, then apply the bender take-up/deduct
>    per conduit size (Mike Holt, *Bending Round Raceways*) so each feed is the
>    real mark, not the centerline corner.
> 7. **Lay it out organized** — per conduit: type, size, length, bend count, and
>    the ordered bend list — as a schedule, as spreadsheets, and as a diagram.
> Let me show you the output."

---

## 1 — The bend schedule (the main thing)  ⭐
```bash
python3 bim/process.py bim/samples/sample_elec.ifc
```
> **Say:** "This is the bend schedule for a whole building — Revit's sample
> electrical project. Every conduit run is one row: what conduit it is, how long
> it is, and how many bends. Notice the lengths — this run is 180 feet, so it's
> not one 10-foot stick, it's many sticks coupled into one run. And down here is
> the detail for each run: in order, how far you feed, the bend angle, and the
> roll — that's the recipe to actually bend it."

*(Point at the SUMMARY table — a couple of runs and their bend counts — then a DETAIL block.)*

---

## 2 — The same data as spreadsheets (open in Excel)
> **Say:** "And it writes that out as spreadsheets, so anyone can open, sort, and
> filter it."

Open **`bim/out/sample_elec_runs.csv`** (one row per conduit) and
**`bim/out/sample_elec_bends.csv`** (one row per bend) — or click them from `index.html`.
> **Say:** "One sheet is one row per conduit — size, length, number of bends. The
> other is one row per bend — feed length, angle, roll. This is the format that
> drops straight into a fab workflow."

---

## 3 — See it: a diagram per run
```bash
open bim/out/sample_elec_diagrams.html   # (already made in step 1; or click from index.html)
```
> **Say:** "And to actually see each run — this draws every conduit in 3D. Green is
> the start and end, each red dot is a bend labeled with its angle. So you can look
> at a run and immediately see its shape and where it bends, right next to the
> numbers in the schedule."

*(Scroll the gallery; point at one run's bends.)*

---

## 4 — It feeds the machine (the endpoint)
```bash
python3 run_demo.py bim/out/sample_elec_job.json
```
> **Say:** "And because the data's structured, it drives the machine directly —
> the most complex run, organized into 10-ft sticks with take-up-corrected feeds,
> runs end to end through our machine simulator as real firmware commands. Each
> stick is load-at-zero, advance, bend, roll — exactly the machine's vocabulary.
> So the whole path works: BIM model → organized, fabrication-ready bend data →
> machine."

---

## 5 — It's solid (credibility)
```bash
python3 bim/test_extract_conduit.py
```
> **Say:** "And all of this is covered by a test suite, including tests on the real
> Revit files — 15 out of 15 pass."

---

## Honest caveats (say them — they build trust)
- Feeds carry the **take-up/deduct** for each conduit size (bend-shoe radius from
  NEC Ch.9 Table 2 — confirm against the shop's actual Greenlee 555 shoes). Still
  **not calibrated** to motor steps / springback (a tuning step on the real
  machine, with the team).
- Validated on a full orthogonal building; a true 3D saddle and the
  **trade-size → die** mapping are next.
- The few odd angles in the schedule are **left flagged on purpose**, not faked.

## If they ask
- *"How is this different from just opening the Revit model?"* → "Revit shows you
  the conduit; it doesn't give you the *bend recipe*. We turn the geometry into the
  feed-lengths, angles, and rolls a machine (or a person) bends from — organized
  per conduit."
- *"Real or made-up data?"* → "This is Revit's real sample building — 530 conduit
  pieces. I also drew a simple one to check the math."
- *"Can it run the real machine now?"* → "It produces the bend recipe and runs in
  the simulator today; real hardware needs calibration + the machine-control side."
- *"How much is you vs. AI?"* → "I used AI tooling to move fast, but I drove every
  step and understand each piece — happy to dig into any part."
