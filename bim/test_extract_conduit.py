"""Tests for the conduit extractor — locks in the behaviour built against the
synthetic fixtures so future changes can't silently regress it.

Run either way (no pytest required):
    python3 bim/test_extract_conduit.py
    python3 -m pytest bim/test_extract_conduit.py
"""

import contextlib
import io
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # so 'import extract_conduit' works from anywhere

import ifcopenshell
import ifcopenshell.util.unit
import extract_conduit as ec
import bend_report as br
import make_sample_ifc
import make_scattered_ifc
import make_fitting_ifc


def _mm_scale(model):
    try:
        return ifcopenshell.util.unit.calculate_unit_scale(model) * 1000.0
    except Exception:
        return 1.0


def _generate(module):
    with contextlib.redirect_stdout(io.StringIO()):
        module.main()


def runs_bends(path):
    """Re-run the extractor pipeline; return [bends_per_run], longest run first."""
    model = ifcopenshell.open(path)
    scale = _mm_scale(model)
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    runs = [r for r in ec.group_into_runs(segs + fits, scale=scale) if len(r) >= 2]
    out = []
    for run in runs:
        bends, _, _ = ec.derive_bends(ec.simplify_polyline(run, ec.SIMPLIFY_TOL))
        out.append(bends)
    return out


def approx(a, b, tol=0.6):
    return abs(a - b) <= tol


# ── function-level ───────────────────────────────────────────────────────────
def test_simplify_removes_noise_keeps_corner():
    pts = [(float(x), 0.4 if k % 2 == 0 else -0.4, 0.0)
           for k, x in enumerate(range(0, 1001, 50))]
    pts.append((1000.0, 500.0, 0.0))                 # one real 90-degree corner
    raw, _, _ = ec.derive_bends(pts)
    simp, _, _ = ec.derive_bends(ec.simplify_polyline(pts, ec.SIMPLIFY_TOL))
    assert len(raw) > 5                              # noise reads as many bends
    assert len(simp) == 1                            # simplify leaves the real one
    assert approx(simp[0]["angle"], 90.0)


def test_derive_bends_offset():
    verts = [(0, 0, 0), (300, 0, 0), (450, 150, 0), (750, 150, 0)]
    bends, _, _ = ec.derive_bends(verts)
    assert len(bends) == 2
    assert approx(bends[0]["angle"], 45) and approx(bends[1]["angle"], 45)
    assert approx(bends[1]["rotate"], 180)           # second bend flips the plane


# ── pipeline on generated fixtures ───────────────────────────────────────────
def test_sample_axis():
    _generate(make_sample_ifc)
    runs = runs_bends(os.path.join(HERE, "sample_conduit.ifc"))
    assert len(runs) == 1
    angles = [b["angle"] for b in runs[0]]
    assert len(angles) == 2 and all(approx(a, 45) for a in angles)


def test_scattered_regroups_two_runs():
    _generate(make_scattered_ifc)
    runs = runs_bends(os.path.join(HERE, "scattered_conduit.ifc"))
    assert len(runs) == 2                            # shuffled pieces -> 2 real runs
    assert len(runs[0]) == 2 and all(approx(b["angle"], 45) for b in runs[0])
    assert any(len(r) == 1 and approx(r[0]["angle"], 90) for r in runs)


def test_fitting_connects_the_run():
    _generate(make_fitting_ifc)
    path = os.path.join(HERE, "fitting_conduit.ifc")
    model = ifcopenshell.open(path)
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    assert len(ec.group_into_runs(segs)) == 2        # segments alone: disconnected
    assert len(ec.group_into_runs(segs + fits)) == 1  # the fitting stitches them
    runs = runs_bends(path)
    assert len(runs) == 1 and len(runs[0]) == 1 and approx(runs[0][0]["angle"], 90)


# ── real downloaded files (skipped if not present) ───────────────────────────
def test_ifc2x3_does_not_crash_and_splits_runs():
    path = os.path.join(HERE, "samples", "project1.ifc")
    if not os.path.exists(path):
        return
    model = ifcopenshell.open(path)
    assert model.schema == "IFC2X3"
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    assert len(segs) == 2                            # found via type (not a crash)
    assert len(runs_bends(path)) == 2                # two separate pieces, no fake bend


def test_metres_file_normalized_to_mm():
    path = os.path.join(HERE, "samples", "435--cableCarrier--abort.ifc")
    if not os.path.exists(path):
        return
    assert _mm_scale(ifcopenshell.open(path)) == 1000.0  # metres -> mm


def test_revit_conduit_port_based():
    """Real Revit export: 'conduit without fittings' leaves bend-radius gaps
    between straights and unreadable MappedRepresentation elbows, so geometric
    endpoint-matching finds 0 bends. Port-based grouping must recover the run."""
    path = os.path.join(HERE, "samples", "conduit_dtv.ifc")
    if not os.path.exists(path):
        return
    model = ifcopenshell.open(path)
    scale = _mm_scale(model)
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")

    # geometry-only grouping fails here (gaps) — that's why ports are needed
    geo = ec.group_into_runs(segs + fits, scale=scale)
    assert all(len(ec.derive_bends(r)[0]) == 0 for r in geo)

    # port-based grouping stitches the one real run and finds both 90° bends
    runs = ec.port_based_runs(model, segs, fits, scale=scale)
    assert len(runs) == 1
    bends, _, _ = ec.derive_bends(runs[0])
    assert len(bends) == 2
    assert all(approx(b["angle"], 90) for b in bends)


def test_revit_all_three_exports_agree():
    """All three IFC export setups (2x3 / Reference / Design Transfer) should
    yield the same two 90° bends — the conduit centerline survives every MVD."""
    angles_per_file = []
    for name in ("conduit_2x3", "conduit_ref", "conduit_dtv"):
        path = os.path.join(HERE, "samples", f"{name}.ifc")
        if not os.path.exists(path):
            return
        model = ifcopenshell.open(path)
        scale = _mm_scale(model)
        segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
        fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
        runs = ec.port_based_runs(model, segs, fits, scale=scale)
        assert len(runs) == 1
        bends, _, _ = ec.derive_bends(runs[0])
        angles_per_file.append([round(b["angle"]) for b in bends])
    assert angles_per_file[0] == angles_per_file[1] == angles_per_file[2] == [90, 90]


# ── trade-angle cleanup ──────────────────────────────────────────────────────
def test_snap_to_trade_angles():
    assert ec.snap_to_trade(44.2) == 45.0
    assert ec.snap_to_trade(30.4) == 30.0
    assert ec.snap_to_trade(88.0) == 90.0      # within 4° -> snaps
    assert ec.snap_to_trade(37.0) == 37.0      # 7° from nearest -> left alone
    assert ec.snap_to_trade(2.0) == 2.0        # snap never invents a bend
    # relative guard: a gentle bend isn't forced up to the 10° trade floor
    assert ec.snap_to_trade(6.0) == 6.0        # 4° move is 2/3 of a 6° bend -> keep
    assert ec.snap_to_trade(14.0) == 14.0      # 4° move is too big relative to 14°
    assert ec.snap_to_trade(9.5) == 10.0       # 0.5° move near the floor still snaps
    # force=True (the "resolve odd angles" action) snaps to nearest trade unconditionally
    assert ec.snap_to_trade(6.0, force=True) == 10.0
    assert ec.snap_to_trade(82.6, force=True) == 90.0
    assert ec.snap_to_trade(52.0, force=True) == 45.0


def test_drop_near_straight_removes_tiny_kink():
    pts = [(0, 0, 0), (1000, 0, 0), (2000, 35, 0), (2000, 1035, 0)]  # ~2° then ~90°
    raw, _, _ = ec.derive_bends(pts)
    assert len(raw) == 2                        # the tiny kink reads as a bend
    cleaned = ec.drop_near_straight(pts, ec.MIN_BEND_DEG)
    b, _, _ = ec.derive_bends(cleaned)
    assert len(b) == 1                          # kink dropped, only the real corner
    assert ec.snap_to_trade(b[0]["angle"]) == 90.0


def test_building_gnarly_run_cleans_to_trade_angles():
    """The most-bent run in the real Sample Electrical Project cleans from 13 raw
    bends (incl. two ~2° artifacts) to 11 standard trade-angle bends."""
    path = os.path.join(HERE, "samples", "sample_elec.ifc")
    if not os.path.exists(path):
        return
    model = ifcopenshell.open(path)
    scale = _mm_scale(model)
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    runs = ec.port_based_runs(model, segs, fits, scale=scale)

    def clean(run):
        poly = ec.drop_near_straight(ec.simplify_polyline(run, ec.SIMPLIFY_TOL), ec.MIN_BEND_DEG)
        b, _, _ = ec.derive_bends(poly)
        return [round(ec.snap_to_trade(x["angle"]), 1) for x in b]

    angles = clean(max(runs, key=lambda r: len(clean(r))))
    assert angles == [90, 60, 30, 45, 45, 30, 30, 45, 45, 30, 90]
    assert all(a in ec.TRADE_ANGLES for a in angles)


def test_outer_diameter_and_kind_from_geometry():
    """Trade size isn't in a pset on these exports; it must be read from the
    conduit's circular cross-section. Sample building is 2\" EMT (OD ~55.8 mm)."""
    path = os.path.join(HERE, "samples", "sample_elec.ifc")
    if not os.path.exists(path):
        return
    model = ifcopenshell.open(path)
    scale = _mm_scale(model)
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    od = ec.outer_diameter(segs[0])
    assert od is not None and approx(od * scale, 55.8, tol=1.0)
    assert "EMT" in (ec.conduit_kind(segs[0]) or "")


def test_split_into_pieces_respects_stick_and_couplers():
    # a ~26 ft run: 90 near the start, a long straight, then two bends
    bends = [{"advance": 1000.0, "rotate": 0.0, "angle": 90.0},
             {"advance": 5000.0, "rotate": 90.0, "angle": 45.0},
             {"advance": 1000.0, "rotate": 180.0, "angle": 45.0}]
    pieces, warns = ec.split_into_pieces(bends, tail=1000.0)
    assert not warns
    assert len(pieces) >= 3                              # 26 ft -> at least 3 sticks
    assert all(p["length_mm"] <= ec.STICK_MM + 1 for p in pieces)   # none over 10 ft
    # every bend is preserved, none lands on a coupler (couplers are in straights)
    assert sum(len(p["bends"]) for p in pieces) == 3
    # interior pieces are coupled on both ends; the run's two outer ends are free
    assert pieces[0]["start_coupler"] is False and pieces[-1]["end_coupler"] is False


def test_split_building_runs_all_within_a_stick():
    path = os.path.join(HERE, "samples", "sample_elec.ifc")
    if not os.path.exists(path):
        return
    model = ifcopenshell.open(path)
    scale = _mm_scale(model)
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    over = 0
    for run in ec.port_based_runs(model, segs, fits, scale=scale):
        poly = ec.drop_near_straight(ec.simplify_polyline(run, ec.SIMPLIFY_TOL), ec.MIN_BEND_DEG)
        bends, _, tail = ec.derive_bends(poly)
        pieces, _ = ec.split_into_pieces(bends, tail)
        over += sum(1 for p in pieces if p["length_mm"] > ec.STICK_MM + 1)
    assert over == 0                                     # no piece exceeds a 10-ft stick


def test_bend_radius_lookup_by_od():
    # ODs that appear in the real exports -> the trade size a shop would read
    assert ec.trade_size_for_od(23.4) == "3/4"
    assert ec.trade_size_for_od(29.5) == "1"
    assert ec.trade_size_for_od(55.8) == "2"
    assert ec.trade_size_for_od(60.3) == "2"      # RNC 2" OD, still 2" trade size
    assert ec.trade_size_for_od(168.3) == "6"
    assert ec.trade_size_for_od(None) is None
    # 1" shoe radius is NEC Ch.9 Table 2's 5.75 in
    assert approx(ec.bend_radius_mm(29.5), 5.75 * 25.4, tol=0.1)
    assert ec.bend_radius_mm(None) == 0.0          # unknown OD -> no correction


def test_takeup_correction_shortens_feed_and_cut_length():
    # one 90° bend, 1000 mm straight each side (~6.6 ft total -> a single stick)
    bends = [{"advance": 1000.0, "rotate": 0.0, "angle": 90.0}]
    R = ec.bend_radius_mm(29.5)                     # 1" EMT shoe
    pieces, _ = ec.split_into_pieces(bends, tail=1000.0, radius_mm=R)
    assert len(pieces) == 1
    p = pieces[0]
    b = p["bends"][0]
    # take-up for a 90° is exactly the radius; the mark moves back by it
    assert approx(b["takeup_mm"], R, tol=0.1)
    assert approx(b["feed"], 1000.0 - R, tol=0.1)  # shortened, not the raw 1000
    assert approx(p["tail_mm"], 1000.0 - R, tol=0.1)
    assert approx(b["arc_mm"], R * math.pi / 2, tol=0.1)
    # developed (cut) length = two straights + the arc, less than the sharp span
    expect_dev = 2 * (1000.0 - R) + R * math.pi / 2
    assert approx(p["developed_mm"], expect_dev, tol=0.2)
    assert p["developed_mm"] < p["length_mm"]      # the bend "gain"


def test_no_radius_leaves_sharp_geometry_unchanged():
    bends = [{"advance": 1000.0, "rotate": 0.0, "angle": 90.0}]
    pieces, _ = ec.split_into_pieces(bends, tail=1000.0)   # radius_mm defaults to 0
    p = pieces[0]
    assert p["bends"][0]["feed"] == 1000.0 and p["bends"][0]["takeup_mm"] == 0.0
    assert p["tail_mm"] == 1000.0
    assert approx(p["developed_mm"], p["length_mm"], tol=0.1)   # no gain without a radius


def test_load_job_accepts_per_stick_and_flat():
    """The simulator loader runs both the legacy flat job and the BIM pipeline's
    per-stick job (pieces flattened in order; straight sticks contribute none)."""
    import json
    import tempfile
    sys.path.insert(0, os.path.dirname(HERE))      # project root, for 'programs'
    try:
        from programs.bend_job import load_job
    except ModuleNotFoundError:
        return   # machine-drive layer not present (standalone engine repo)

    def write(obj):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(obj, f)
        f.close()
        return f.name

    pieces_job = write({"pieces": [
        {"piece": 1, "bends": [{"advance": 100.0, "rotate": 0.0, "angle": 90.0}]},
        {"piece": 2, "bends": [], "tail_advance": 3048.0},          # straight stick
        {"piece": 3, "bends": [{"advance": 80.0, "rotate": 180.0, "angle": 45.0}]},
    ]})
    flat_job = write({"bends": [{"advance": 300, "rotate": 0, "angle": 90}]})

    pb = load_job(pieces_job)
    assert [b.angle for b in pb] == [90.0, 45.0]    # the straight stick adds nothing
    assert pb[0].advance == 100.0 and pb[1].rotate == 180.0
    assert len(load_job(flat_job)) == 1             # legacy flat shape still loads


def test_split_polyline_cuts_run_into_sticks():
    import bend_diagram as bd
    # an L-shaped run: 1000 mm east, then 1000 mm north (a 90° corner at the bend)
    verts = [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0)]
    sticks, couplers = bd.split_polyline(verts, [500.0, 1500.0])
    assert len(sticks) == 3 and len(couplers) == 2     # two cuts -> three sticks
    # couplers land on the line at the cut distances, not on the bend
    assert approx(couplers[0][0], 500.0) and approx(couplers[0][1], 0.0)
    assert approx(couplers[1][0], 1000.0) and approx(couplers[1][1], 500.0)
    # the corner (the bend vertex) sits inside the middle stick
    assert any(approx(v[0], 1000.0) and approx(v[1], 0.0) for v in sticks[1])


def test_qa_flags_odd_angles_not_clean_runs():
    import qa
    assert qa._is_trade(90.0) and qa._is_trade(22.5)
    assert not qa._is_trade(6.0) and not qa._is_trade(82.6)   # kept-honest odd angles
    # conduit_dtv is a clean synthetic run (two 90° bends) — nothing to flag
    path = os.path.join(HERE, "samples", "conduit_dtv.ifc")
    if os.path.exists(path):
        _, _, flagged = qa.audit(path)
        assert flagged == [], f"clean run should not be flagged, got {flagged}"


def test_qa_flags_bent_run_with_unknown_size():
    """A run that bends but has no readable OD can't be take-up corrected or given a
    die, so it MUST be flagged (not silently shipped). A straight run with no OD is
    not a fabrication job, so it must NOT be flagged for size."""
    import qa
    unknown_bent = [{"run": 1, "kind": "?", "od_mm": None, "length_mm": 3000.0,
                     "bends": [{"advance": 500.0, "angle": 90.0, "rotate": 0.0, "roll_dir": 0}],
                     "tail_mm": 500.0, "pieces": [], "piece_warnings": []}]
    flagged = qa.flag_rows(unknown_bent, {})
    assert flagged and any(i.startswith("unknown size") for i in flagged[0]["issues"])
    n_size, _, _, _ = qa.counts(flagged)
    assert n_size == 1
    # straight run, unknown OD -> nothing to bend, so no size flag
    straight = [{"run": 1, "kind": "?", "od_mm": None, "length_mm": 3000.0,
                 "bends": [], "tail_mm": 0.0, "pieces": [], "piece_warnings": []}]
    assert qa.flag_rows(straight, {}) == []


def test_pipeline_robust_across_all_sample_ifcs():
    """Every sample IFC (electrical, HVAC, plumbing, test fixtures, the full
    building) must parse without raising, and known ones hit expected counts."""
    import glob
    samples = sorted(glob.glob(os.path.join(HERE, "samples", "*.ifc")))
    assert samples, "no sample IFCs found"
    counts = {}
    for path in samples:
        _info, rows = br.run_rows(path)              # must not raise on any file
        assert isinstance(rows, list)
        counts[os.path.basename(path)] = len(rows)
    # non-electrical models have no conduit; the sample building has many
    if "Building-Hvac.ifc" in counts:
        assert counts["Building-Hvac.ifc"] == 0
    if "conduit_dtv.ifc" in counts:
        assert counts["conduit_dtv.ifc"] == 1
    if "sample_elec.ifc" in counts:
        assert counts["sample_elec.ifc"] > 100


def test_run_rows_falls_back_to_geometry_without_ports():
    """A real export with no IFC connection ports must still be reconstructed from
    raw centerline geometry, not silently dropped. The cableCarrier 'abort' file has
    no usable ports but a single 81-point swept-disk segment that bends 10 times."""
    path = os.path.join(HERE, "samples", "435--cableCarrier--abort.ifc")
    if not os.path.exists(path):
        return
    import ifcopenshell, ifcopenshell.util.unit as U
    m = ifcopenshell.open(path)
    scale = U.calculate_unit_scale(m) * 1000.0
    segs = ec.occurrences_of(m, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(m, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    # ports give nothing here; the shared reconstruction must fall back to geometry
    assert ec.port_based_runs(m, segs, fits, scale=scale, return_segments=True) == []
    assert ec.reconstruct_runs(m, segs, fits, scale=scale), "geometry fallback found nothing"
    _info, rows = br.run_rows(path)
    assert any(r["bends"] for r in rows), "no bends recovered from a port-less file"


def test_cable_trays_excluded_conduit_kept():
    """Cable trays/ladders/trunking share IfcCableCarrierSegment with conduit but
    aren't bendable here — they must be excluded (by PredefinedType), while real
    conduit is kept. project1 is a CABLETRAYSEGMENT file; conduit_dtv is conduit."""
    import ifcopenshell
    tray = os.path.join(HERE, "samples", "project1.ifc")
    if os.path.exists(tray):
        m = ifcopenshell.open(tray)
        segs, _fits, n_trays = ec.conduit_elements(m)
        assert segs == [] and n_trays >= 1, "cable trays should be excluded"
        _info, rows = br.run_rows(tray)
        assert rows == [], "a tray-only file should produce no conduit runs"
    conduit = os.path.join(HERE, "samples", "conduit_dtv.ifc")
    if os.path.exists(conduit):
        m = ifcopenshell.open(conduit)
        segs, _fits, n_trays = ec.conduit_elements(m)
        assert len(segs) >= 1 and n_trays == 0, "conduit must be kept, not skipped"


def test_short_kind_does_not_leak_raw_names():
    """The 'kind' label uses the trade abbreviation; a raw or non-Latin element name
    must not leak through (a Cyrillic tray name becomes generic 'conduit')."""
    assert br.short_kind("Electrical Metallic Tubing (EMT)") == "EMT"
    assert br.short_kind("Rigid Nonmetallic Conduit (RNC Sch 40)") == "RNC Sch 40"
    assert br.short_kind("Ступенчатый кабельный лоток") == "conduit"   # no Latin -> generic
    assert br.short_kind(None) == "?"


def test_port_based_file_still_uses_ports_not_fallback():
    """A file WITH ports must use them, not the weaker geometry grouping: conduit_dtv
    reconstructs to one bent run via ports, though raw endpoint-grouping alone would
    see only straight segments. Guards against the fallback overriding good ports."""
    path = os.path.join(HERE, "samples", "conduit_dtv.ifc")
    if not os.path.exists(path):
        return
    _info, rows = br.run_rows(path)
    assert len(rows) == 1 and rows[0]["bends"], "port-based reconstruction regressed"


def test_run_rows_isolates_a_bad_run():
    """One run that blows up mid-processing is skipped and counted (info['n_errors']),
    never allowed to crash the whole job — real models have the odd degenerate run."""
    path = os.path.join(HERE, "samples", "sample_elec.ifc")
    if not os.path.exists(path):
        return
    orig = ec.split_into_pieces
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:                 # detonate exactly one run
            raise RuntimeError("synthetic bad run")
        return orig(*a, **k)
    ec.split_into_pieces = boom
    try:
        info, rows = br.run_rows(path)
    finally:
        ec.split_into_pieces = orig
    assert info["n_errors"] >= 1, "the bad run should be counted, not raised"
    assert len(rows) > 100, "every other run should still process"


def test_calibration_converters_and_springback():
    import calibration as cal
    assert cal.CALIBRATED is False                        # honest: not yet calibrated
    assert cal.mm_to_steps(100) == 100 * cal.CALIBRATION["advance_steps_per_mm"]
    assert cal.deg_to_steps(90, "bend") == 90 * cal.CALIBRATION["bend_steps_per_deg"]
    assert cal.deg_to_steps(45, "rotate") == 45 * cal.CALIBRATION["rotate_steps_per_deg"]
    assert cal.springback(45) == 45.0                     # zero model = identity for now


def test_calibration_apply_to_job_gated():
    import calibration as cal
    mk = lambda: {"pieces": [{"bends": [{"advance": 100.0, "angle": 90.0,
                                         "rotate": 0.0, "roll_dir": 0}]}]}
    # uncalibrated: no-op, no step fields added
    out = cal.apply_to_job(mk())
    assert "advance_steps" not in out["pieces"][0]["bends"][0]
    # calibrated: bends get motor-step / over-bend values
    cal.CALIBRATED = True
    try:
        out2 = cal.apply_to_job(mk())
        b = out2["pieces"][0]["bends"][0]
        assert b["advance_steps"] == round(cal.mm_to_steps(100.0))
        assert b["bend_steps"] == round(cal.deg_to_steps(cal.springback(90.0), "bend"))
        assert out2["calibrated"] is True
    finally:
        cal.CALIBRATED = False                            # restore for other tests


def test_roundtrip_reconstruct_rebuilds_a_run():
    """A run whose angles are already trade angles should rebuild from its own
    (advance, angle, roll) recipe back onto itself — the round-trip guard."""
    import numpy as np
    import validate as V
    # +X, then 90° up to +Y, then 90° (with a plane roll) to +Z
    verts = [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (1000, 1000, 1000)]
    rebuilt = V.reconstruct(verts)
    dev = max(float(np.linalg.norm(np.array(a, float) - b)) for a, b in zip(verts, rebuilt))
    assert dev < 1.0, f"reconstruction drifted {dev:.2f} mm on exact trade angles"


def test_bends_csv_has_roll_direction_column():
    import csv
    import tempfile
    rows = [{"run": 1, "kind": "EMT", "od_mm": 29.5, "length_mm": 5000.0, "bends": [
        {"advance": 1000.0, "rotate": 0.0, "roll_dir": 0, "angle": 90.0},
        {"advance": 800.0, "rotate": 90.0, "roll_dir": -1, "angle": 45.0}]}]
    runs = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False).name
    bends = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False).name
    br.write_csvs(rows, runs, bends)
    got = list(csv.DictReader(open(bends)))
    assert "roll_dir" in got[0]
    assert got[0]["roll_dir"] == ""          # first bend: no prior plane, no direction
    assert got[1]["roll_dir"] == "CCW"       # rotate 90, roll_dir -1 -> CCW


def test_classify_ops_offset_saddle_and_bends():
    def B(ang, rot, adv=500.0):
        return {"angle": ang, "rotate": rot, "advance": adv, "roll_dir": 1}
    # 90 stub, then a 30 offset (two 30s, 2nd rolled 180, close), then a lone 45
    ops = ec.classify_ops([B(90, 0), B(30, 90), B(30, 180, 600.0), B(45, 0)])
    assert [o["type"] for o in ops] == ["bend", "offset", "bend"]
    assert ops[1]["idx"] == [1, 2] and approx(ops[1]["angle"], 30.0)
    assert approx(ops[1]["rise_mm"], 600.0 * math.sin(math.radians(30)))   # 300 mm
    # Mike Holt offset math: shrink = rise*tan(θ/2), multiplier = 1/sin(θ)
    assert approx(ops[1]["shrink_mm"], 300.0 * math.tan(math.radians(15)))  # ~80.4 mm
    assert approx(ops[1]["multiplier"], 2.0)                                # 30° -> ×2
    # a 90° pair is routing (go/return), NOT an offset — even rolled 180
    assert [o["type"] for o in ec.classify_ops([B(90, 0), B(90, 180)])] == ["bend", "bend"]
    # equal offset-angle bends too far apart -> two separate bends, not an offset
    far = ec.classify_ops([B(30, 0), B(30, 180, ec.STICK_MM + 100)])
    assert [o["type"] for o in far] == ["bend", "bend"]
    # a 3-point saddle: theta, 2*theta, theta with the middle & last flipped
    sad = ec.classify_ops([B(22.5, 0), B(45, 180), B(22.5, 180)])
    assert [o["type"] for o in sad] == ["saddle"] and sad[0]["idx"] == [0, 1, 2]
    # saddle math: rise = center-span * sin(theta); multiplier = cot(theta) (~2.41 for 45°)
    assert sad[0]["center_angle"] == 45.0
    assert approx(sad[0]["rise_mm"], 500.0 * math.sin(math.radians(22.5)))   # ~191 mm
    assert approx(sad[0]["multiplier"], 1.0 / math.tan(math.radians(22.5)))  # ~2.41


def test_roll_direction_is_signed():
    # +X, then +Y (bend up), then +Z: the bend plane rolls one way about the feed
    bends, _, _ = ec.derive_bends([(0, 0, 0), (10, 0, 0), (10, 10, 0), (10, 10, 10)])
    assert len(bends) == 2
    assert bends[0]["roll_dir"] == 0                   # first bend has no prior plane
    assert approx(bends[1]["rotate"], 90.0) and bends[1]["roll_dir"] == 1
    # mirror the last leg to -Z and the roll turns the other way
    bends2, _, _ = ec.derive_bends([(0, 0, 0), (10, 0, 0), (10, 10, 0), (10, 10, -10)])
    assert bends2[1]["roll_dir"] == -1
    # an offset (roll 180) has no handed direction; a 90 roll does
    assert br.roll_dir_word(180.0, 0) == "" and br.roll_label(180.0, 0) == "roll 180"
    assert br.roll_label(90.0, 1) == "roll 90 CW" and br.roll_label(90.0, -1) == "roll 90 CCW"


def test_pack_labeled_cut_plan():
    # three pieces from 3048 mm stock: 3000 fills one; 2000 + 1000 nest into another
    sticks = ec.pack_labeled([("1.1", 3000.0), ("2.1", 2000.0), ("2.2", 1000.0)],
                             stick_mm=3048.0)
    assert len(sticks) == 2                              # offcut nesting -> 2 not 3
    assert all(sum(L for _, L in s) <= 3048.0 + 1 for s in sticks)   # within a stick
    assert sorted(lab for s in sticks for lab, _ in s) == ["1.1", "2.1", "2.2"]  # each once


def test_job_totals_bill_of_materials():
    def B(ang, rot, adv=600.0):
        return {"angle": ang, "rotate": rot, "advance": adv, "roll_dir": 0}
    rows = [
        {"run": 1, "kind": "EMT", "od_mm": 29.5, "bends": [B(30, 0), B(30, 180)],  # an offset
         "pieces": [{"developed_mm": 3048.0}, {"developed_mm": 2000.0}, {"developed_mm": 1000.0}]},
        {"run": 2, "kind": "EMT", "od_mm": 29.5, "bends": [B(90, 0)],
         "pieces": [{"developed_mm": 3048.0}, {"developed_mm": 500.0}]},
        {"run": 3, "kind": "EMT", "od_mm": 55.8, "bends": [],
         "pieces": [{"developed_mm": 3048.0}]},
    ]
    by, g = br.job_totals(rows)
    assert set(by) == {'EMT 1"', 'EMT 2"'}
    one = by['EMT 1"']
    assert one["sticks"] == 5 and one["couplers"] == 3   # (3-1)+(2-1) couplers
    assert one["opt_sticks"] == 4                        # nest the 500mm partial -> 4 not 5
    assert one["bends"] == 3 and one["offsets"] == 1     # run 1's two 30s are one offset
    assert g["sticks"] == 6 and g["couplers"] == 3 and g["bends"] == 3
    assert g["offsets"] == 1 and g["saddles"] == 0


def test_stick_marks_cumulative_along_cut_stick():
    import bend_card as bc
    piece = {"bends": [{"feed": 100.0, "angle": 90.0, "rotate": 0.0, "arc_mm": 50.0},
                       {"feed": 200.0, "angle": 45.0, "rotate": 90.0, "arc_mm": 30.0}],
             "tail_mm": 60.0}
    marks = bc.stick_marks(piece)
    assert approx(marks[0][0], 100.0)                  # first mark = feed1
    assert approx(marks[1][0], 350.0)                  # then + arc1 + feed2 = 100+50+200
    assert marks[1][1]["angle"] == 45.0


def test_build_cards_html_cards_bent_sticks_only():
    import bend_card as bc
    rows = [{"run": 1, "kind": "EMT", "od_mm": 29.5, "pieces": [
        {"bends": [], "tail_mm": 3048.0, "length_mm": 3048.0, "developed_mm": 3048.0,
         "start_coupler": False, "end_coupler": True},
        {"bends": [{"feed": 600.0, "angle": 90.0, "rotate": 0.0, "arc_mm": 200.0}],
         "tail_mm": 400.0, "length_mm": 1200.0, "developed_mm": 1100.0,
         "start_coupler": True, "end_coupler": False}]}]
    out = bc.build_cards_html("demo", rows)
    assert "1 stick(s) to bend across 1 run(s)" in out
    assert "Stick 2 of 2" in out and "bend <b>90" in out
    assert "+ 1 straight stick(s)" in out              # the straight stick is summarized, not carded


def test_fmt_ftin_marks_in_feet_and_inches():
    assert br.fmt_ftin(88.9) == "3-1/2 in"          # 3.5 in, no feet
    assert br.fmt_ftin(1587.5) == "5 ft 2-1/2 in"   # conduit_dtv piece-10 feed
    assert br.fmt_ftin(3048.0) == "10 ft"           # a whole stick, no inches
    assert br.fmt_ftin(0.0) == "0 in"
    assert br.fmt_ftin(25.4) == "1 in"              # exactly 1 in, no fraction
    # rounds to the nearest 1/16 in and carries up to a whole inch
    assert br.fmt_ftin(25.4 - 0.1) == "1 in"


def test_snap_roll():
    assert ec.snap_roll(1.4) == 0.0
    assert ec.snap_roll(179.5) == 180.0
    assert ec.snap_roll(88.5) == 90.0
    assert ec.snap_roll(45.0) == 45.0          # a genuine diagonal roll -> left alone


def test_building_rolls_snap_to_right_angles():
    """This building's conduit is all orthogonal, so every roll should land on a
    right angle once the reconstruction noise is snapped away."""
    path = os.path.join(HERE, "samples", "sample_elec.ifc")
    if not os.path.exists(path):
        return
    model = ifcopenshell.open(path)
    scale = _mm_scale(model)
    segs = ec.occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    fits = ec.occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    for run in ec.port_based_runs(model, segs, fits, scale=scale):
        poly = ec.drop_near_straight(ec.simplify_polyline(run, ec.SIMPLIFY_TOL), ec.MIN_BEND_DEG)
        bends, _, _ = ec.derive_bends(poly)
        for b in bends[1:]:                    # first bend's roll is 0 by definition
            assert ec.snap_roll(b["rotate"]) in (0.0, 90.0, 180.0)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {t.__name__}: {e!r}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
