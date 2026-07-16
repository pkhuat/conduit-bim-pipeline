# Walkthrough — bend cards & the build-sheet story (for the company)

A read-aloud script for showing what we built in response to the last feedback:
organized, fabrication-ready bend data that follows the Mike Holt method, ends in
the Greenlee 555's own vocabulary, and is shown three ways — shape, data, and a
printable card per stick.

## Before the call (1 min)
```bash
python3 bim/process.py bim/samples/sample_elec.ifc   # rebuilds everything -> bim/out/
open bim/out/index.html                              # landing page (all links)
```
Have these tabs open: `index.html`, `sample_elec_cards.html`, `sample_elec_diagrams.html`,
and `sample_elec_pieces.csv`.

---

## 0 — Frame it (say first, ~30 sec)
> "Last time you said: organize the conduit data realistically, give bend
> instructions per piece following the Mike Holt round-raceway method, respect
> that conduit comes in 10-ft sticks with couplers only on straights, and end in
> the Greenlee 555's load-advance-bend-roll form. That's what we built. I'll show
> it three ways — the shape, the data, and a printable card for each stick — and
> they're all the same numbers."

---

## 1 — The bend card (lead with this) ⭐
`open bim/out/sample_elec_cards.html`

> **Say:** "This is the headline. Every stick that needs bending gets a card — a
> printable shop traveler. Take **Run 1, Stick 2**. The bar is the stick laid out
> flat, the way you mark it: load end on the left. The red marks are the bends.
> Above each is the angle, below it the roll — including the direction, CW or CCW.
> On each segment is how far to feed, in real feet-and-inches. The hollow circles
> are couplers, so you can see this stick joins one on each end. Top-right is the
> length to cut it to."

*(Point at Stick 2: feed 3-7/16 in → 30° roll 90 CW; feed 5 ft 10-1/2 in → 45° roll 180; tail 2 ft 7-3/8 in.)*

> **Say:** "And under the picture are the numbered steps — exactly what a
> fabricator, or the 555, executes: load, feed, bend, roll, repeat. Print these
> and you can bend straight from them."

---

## 2 — Same data, three ways (the trust point)
> **Say:** "Here's the important part — the card isn't a separate thing we drew.
> It's one row of the spreadsheet, drawn."

Switch to `sample_elec_pieces.csv`, find **run 1, piece 2**:
```
1,2,19,9.86,9.81,1,1,2,"feed 3-7/16 in, bend 30 (roll 90 CW) ; feed 5 ft 10-1/2 in, bend 45 (roll 180) ; tail 2 ft 7-3/8 in"
```
> **Say:** "Run 1, piece 2 — that's 'Run 1, Stick 2' on the card. Coupler both
> ends, cut 9.81 ft — that's the '9 ft 9-3/4 in' on the card. And the instructions
> column is the card's steps, word for word. The spreadsheet is the data; the card
> is the same row as the physical stick. Nothing added, nothing lost."

Then switch to `sample_elec_diagrams.html`:
> **Say:** "And here's the third view — the run's actual shape in the building.
> Each color band is one 10-ft stick; the hollow marks are the couplers, always on
> a straight. So: the diagram is the shape, the spreadsheet is the data, the card
> is the build sheet — one run, three views, same numbers."

---

## 3 — Following the Mike Holt method (the correctness point)
> **Say:** "Two things make these numbers real and not just geometry. First,
> **take-up** — the feeds are corrected for the bender's shoe radius per the Mike
> Holt round-raceway method, so a mark is where you actually mark it, not the
> centerline corner. Second, it's organized into **10-ft sticks with couplers only
> on straights**, never on a bend — exactly your constraint."

---

## 4 — The job at a glance (the material point)
Back to `index.html` (or the JOB TOTALS in the terminal).
> **Say:** "And it totals the whole job: for this building, **736 sticks, 528
> couplers, about 6,165 feet** of conduit, broken out by size. That's your order
> sheet — it falls straight out of the same data."

---

## 5 — Honest caveats 
> "Two things to lock down with your shop, both one-line changes:
> - The **shoe radii** are NEC standard values right now — give us your actual
>   Greenlee 555 take-up numbers and the feeds match your machine exactly.
> - The roll **direction** (CW vs CCW) is geometrically consistent, but which way
>   is 'CW' should be matched to the machine's roll axis — if it's flipped, it's a
>   single sign change.
>
> Beyond that, springback and motor calibration are tuning steps we'd do on the
> real machine with your team."

---

## If they ask
- *"Is the card the same as the spreadsheet?"* → "Identical — the card is one CSV
  row drawn as the stick. Same feeds, same angles, same rolls, same cut length."
- *"Why are most sticks not on cards?"* → "Only sticks that need bending get a card.
  The straight ones are summarized per run — cut to 10 ft and couple."
- *"Real building?"* → "Revit's real sample electrical project — 208 runs, 530+
  conduit pieces. The small hand-built one (conduit_dtv) is there to check the math."
- *"Can it run the machine?"* → "It produces the per-stick recipe and runs in our
  simulator today; the real machine needs calibration and the roll/shoe confirmation."
