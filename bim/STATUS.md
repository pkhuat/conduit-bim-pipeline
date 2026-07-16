# Status — Getting Conduit Data from BIM (my part / Step 1)

Quick, informal status of where I'm at on the BIM side of the project.

## What my part is
Step 1: get the conduit bend data out of a building's BIM model so our machine
can use it. I'm not modeling anything — I'm building the thing that *reads* the
data and turns it into bend instructions our machine runs. (Step 2, parsing the
data and actually driving the machine, is Josh's side.)

## The options for getting the data
1. **Export the model to IFC** (an open file format) and read it ourselves — most flexible, not locked to one software.
2. **Use Revit's API directly** — more accurate, but locked to Revit and needs more dev.
3. **Tap the spool software** contractors already use (Allied BIM, Stratus, Greenlee BendWorks, EVOLVE) — they already turn BIM into bend instructions, so their output is basically what we need, but it depends on the contractor using one.

I'm going with the IFC route first since it's the most independent (matches us wanting to do it ourselves first).

## What I built
A tool that opens an IFC file, finds the conduit, reads its centerline, and
outputs bend instructions (advance / rotate / angle) in the same format our
machine simulator runs. So the whole path works end to end on a test file:
**BIM file in → bend instructions out → runs in the sim.**

It already handles a bunch of real-world messiness:
- reads both **IFC4 and IFC2x3** (the older version Revit exports a lot — it stores conduit differently, and the tool used to crash on it; fixed),
- handles the different ways geometry gets stored (centerline, swept tube, extruded body),
- reads the file's **real units** (mm vs metres vs feet — Revit uses feet).

## What I learned (the important stuff)
- **Export settings matter a lot.** One setting keeps the centerline we need; another just gives a useless 3D mesh. So part of the answer is just making sure whoever exports it uses the right setting.
- **Reading the conduit is the easy part — connecting it is the hard part.** I tested on a real Revit file and the conduit pieces come scattered all over the building, *not* as neat connected runs. My tool naively strung two unrelated pieces together and invented a fake bend. So the real work is **grouping the pieces into actual runs** before working out the bends. That's my next big problem.
- **Good public test files basically don't exist.** I searched a lot — real conduit models live inside companies' Revit files, not online. So I need to make my own test data in Revit.

## Where I'm blocked
I need real conduit data *with actual bends* to keep going, and that needs Revit.
Revit only runs on Windows and I'm on a Mac.

## What I'm doing about it
- Requested access to **Colby's Apporto cloud Windows lab** so I can run Revit from my Mac (waiting on ITS).
- Company is also getting me a **Windows laptop**.
- Lining up the free **Autodesk student license**.

Once I have Revit: make my own conduit models, export them, test which export
setting reads best, then build the "group the pieces into runs" logic against
real data.

## Bottom line
The reader tool is in good shape — it already does BIM file → bend instructions
→ machine sim, and it survives real-world IFC. I'm now mostly waiting on Revit
access to feed it real data and solve the last hard piece (connecting the runs).
