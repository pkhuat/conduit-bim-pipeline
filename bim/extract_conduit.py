"""Read conduit out of an IFC file and derive a bend job from its centerline.

This is roadmap step 5 in miniature: it finds the conduit (IfcCableCarrierSegment),
recovers each piece's centerline, stitches them together, and turns the corners
into (advance, rotate, angle) bends -- the exact format programs/bend_job.py
already speaks. It then writes that job to JSON so you can run it straight
through the simulator:

    python3 bim/make_sample_ifc.py            # creates bim/sample_conduit.ifc
    python3 bim/extract_conduit.py            # reads it, writes bim/derived_job.json
    python3 run_demo.py bim/derived_job.json  # runs the derived job in the sim

Point it at a real export later:  python3 bim/extract_conduit.py path/to/real.ifc

Real exports store conduit geometry in different forms; this reads the three we
have actually seen (see bim/RESEARCH.md):
  - 'Axis' polyline           -> the centerline, used directly
  - IfcSweptDiskSolid         -> the Directrix curve IS the centerline
  - IfcExtrudedAreaSolid      -> straight section; centerline = the extrusion axis
A tessellated mesh has no centerline and is reported as unsupported.

IMPORTANT -- this is a first-pass derivation with known simplifications, called
out in the output. It is not calibrated and must be reviewed with the team
before it ever drives hardware.
"""

import json
import math
import os
import sys

import numpy as np
import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit

DEFAULT_IFC = os.path.join(os.path.dirname(__file__), "sample_conduit.ifc")
OUT_JOB = os.path.join(os.path.dirname(__file__), "derived_job.json")
STRAIGHT_TOL_DEG = 0.5  # turns smaller than this are treated as "no bend"
SIMPLIFY_TOL = 1.0      # RDP tolerance (model units): collapse centerline noise
# Standard electrician bend angles (deg) — from the V2 spec's bend library.
# Derived angles are snapped to these so output matches the trade vocabulary.
TRADE_ANGLES = (10.0, 22.5, 30.0, 45.0, 60.0, 90.0)
SNAP_TOL_DEG = 4.0      # snap a derived angle to a trade angle within this window
# ...but also require the change to be small RELATIVE to the angle, so a genuine
# gentle bend (e.g. 6°) isn't forced up to the 10° trade floor — a 4° move is
# noise on an 88° bend but two-thirds of a 6° bend. Round-trip validation showed
# small-angle over-snapping swinging long runs' endpoints by feet.
SNAP_REL_TOL = 0.15
MIN_BEND_DEG = 5.0      # gentler than this = routing slack, not a bend to make
# Roll (bend-plane change) for orthogonal conduit is a multiple of 90°; snap the
# reconstruction noise to the nearest within a tight window, leave the rest.
ROLL_ANGLES = (0.0, 90.0, 180.0)   # derive_bends' rotate is unsigned, so 0..180
ROLL_SNAP_TOL_DEG = 3.0
# Physical fabrication limits (conduit is bent one stick at a time, then coupled).
STICK_FT = 10.0                    # conduit comes in 10-ft sticks
STICK_MM = STICK_FT * 304.8
# A coupler must sit in a straight, this far clear of any bend (and a straight
# must be at least 2x this to host one). ASSUMPTION — confirm with the shop.
COUPLER_CLEARANCE_MM = 152.4       # 6 inches

# --- Bend take-up / deduct correction (Mike Holt, "Bending Round Raceways") ---
# We model each bend as a sharp corner at a vertex, so the vertex-to-vertex "advance"
# overshoots reality: a real bend rides an arc of the bender's shoe radius R, tangent to
# both legs. The MARK for a bend therefore sits back from the corner by the take-up
#     t = R * tan(angle/2)          (for a 90° this is just R — the classic "deduct")
# and the arc itself uses  R * angle(rad)  of material; the length saved vs. the sharp
# corner is the "gain" = 2t - arc. We subtract these set-backs from each per-stick feed so
# the feed/marks match the bend a Greenlee 555 actually makes, and report the developed
# (cut) length = straights + arcs.
#
# R is the shoe's centerline radius, by trade size. Seeded from NEC Chapter 9, Table 2
# ("Radius to Center of Field Bends — Other Bends" — the one-shot/power-bender column a
# 555 follows). ASSUMPTION — confirm against the shop's actual 555 shoes; change a value
# and everything downstream re-derives.
# trade size (in) -> (representative OD mm for matching, centerline radius in)
_TRADE_BEND_RADIUS = {
    "1/2":   (19.0,   4.0),
    "3/4":   (24.3,   4.5),
    "1":     (30.5,   5.75),
    "1-1/4": (39.2,   7.25),
    "1-1/2": (45.0,   8.25),
    "2":     (57.0,   9.5),
    "2-1/2": (72.0,   10.5),
    "3":     (87.5,   13.0),
    "3-1/2": (100.5,  15.0),
    "4":     (113.0,  16.0),
    "5":     (141.3,  24.0),
    "6":     (168.3,  30.0),
}
IN_MM = 25.4


def trade_size_for_od(od_mm):
    """Nearest standard trade size (key into _TRADE_BEND_RADIUS) for an outer
    diameter in mm, or None if unknown. Nearest-OD match works across conduit
    families (EMT/RMC/RNC): trade size tracks OD closely enough to pick a shoe."""
    if not od_mm:
        return None
    return min(_TRADE_BEND_RADIUS, key=lambda k: abs(_TRADE_BEND_RADIUS[k][0] - od_mm))


def bend_radius_mm(od_mm):
    """Centerline bend-shoe radius (mm) for a conduit of this OD, or 0.0 if
    unknown — callers then skip the correction and fall back to sharp-corner
    geometry."""
    size = trade_size_for_od(od_mm)
    return _TRADE_BEND_RADIUS[size][1] * IN_MM if size else 0.0


def die_label(kind, od_mm):
    """The Greenlee 555 bending shoe/die to load for this conduit. On a 555 the
    shoe is picked by conduit material + trade size (not a part number), so the
    die is exactly that: e.g. ('EMT', 55.8) -> 'EMT 2"'. Returns '?' if unknown."""
    size = trade_size_for_od(od_mm)
    kind = (kind or "").strip()
    if size and kind:
        return f'{kind} {size}"'
    return kind or (f'{size}"' if size else "?")


# --- tiny 3D vector helpers ----------------------------------------------------
def sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def norm(a):
    return math.sqrt(sum(x * x for x in a))


def unit(a):
    n = norm(a)
    return tuple(x / n for x in a) if n > 1e-9 else (0.0, 0.0, 0.0)


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def angle_between(a, b):
    d = max(-1.0, min(1.0, dot(unit(a), unit(b))))
    return math.degrees(math.acos(d))


# --- geometry / placement ------------------------------------------------------
def _placement_matrix(element):
    """4x4 world transform for an element's ObjectPlacement (identity if none)."""
    if getattr(element, "ObjectPlacement", None):
        return ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    return np.eye(4)


def _axis2placement_matrix(placement):
    """4x4 transform for an IfcAxis2Placement3D (the profile plane of an extrusion)."""
    if placement is None:
        return np.eye(4)
    loc = np.array(placement.Location.Coordinates, dtype=float)
    z = np.array(placement.Axis.DirectionRatios, float) if placement.Axis else np.array([0., 0., 1.])
    x = np.array(placement.RefDirection.DirectionRatios, float) if placement.RefDirection else np.array([1., 0., 0.])
    z = z / np.linalg.norm(z)
    x = x - np.dot(x, z) * z
    x = x / np.linalg.norm(x) if np.linalg.norm(x) > 1e-9 else np.array([1., 0., 0.])
    y = np.cross(z, x)
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = x, y, z, loc
    return M


def _apply(M, p):
    v = np.array([p[0], p[1], p[2] if len(p) > 2 else 0.0, 1.0])
    return tuple(float(c) for c in (M @ v)[:3])


def _polyline_points(curve):
    """Points of an IfcPolyline, else None (other curve types not handled yet)."""
    if curve and curve.is_a("IfcPolyline"):
        return [tuple(float(c) for c in p.Coordinates) for p in curve.Points]
    return None


def segment_centerline(segment):
    """Return (world_points, source_label) for a conduit segment's centerline.

    Tries, in order: an 'Axis' polyline, a swept-disk directrix, an extrusion
    axis. If none apply, returns ([], <geometry-type-label>) so the caller can
    report why a segment yielded no centerline.
    """
    M = _placement_matrix(segment)
    rep = getattr(segment, "Representation", None)
    if not rep:
        return [], "no geometry"

    # 1) explicit centerline
    for shape in rep.Representations:
        if getattr(shape, "RepresentationIdentifier", None) == "Axis":
            for item in shape.Items:
                pts = _polyline_points(item)
                if pts:
                    return [_apply(M, p) for p in pts], "Axis"

    # 2) swept solids (the Body of a real conduit segment)
    for shape in rep.Representations:
        for item in shape.Items:
            if item.is_a("IfcSweptDiskSolid"):
                pts = _polyline_points(item.Directrix)
                if pts:
                    return [_apply(M, p) for p in pts], "SweptDiskSolid"
            if item.is_a("IfcExtrudedAreaSolid"):
                depth = float(item.Depth)
                d = item.ExtrudedDirection.DirectionRatios
                d = np.array([d[0], d[1], d[2] if len(d) > 2 else 0.0], float)
                if np.linalg.norm(d) > 0:
                    d = d / np.linalg.norm(d)
                    MM = M @ _axis2placement_matrix(item.Position)
                    s = _apply(MM, (0.0, 0.0, 0.0))
                    e = _apply(MM, (d[0] * depth, d[1] * depth, d[2] * depth))
                    return [s, e], "ExtrudedAreaSolid"

    # 3) unsupported (e.g. tessellated mesh) — report the representation type
    kinds = [getattr(s, "RepresentationType", None) for s in rep.Representations]
    kinds = [k for k in kinds if k]
    return [], (f"unsupported: {'/'.join(kinds)}" if kinds else "unknown")


# --- IFC reading ---------------------------------------------------------------
def safe_by_type(model, name):
    """by_type that returns [] instead of raising when the entity name isn't
    part of this file's schema (e.g. IfcCableCarrierSegment is an IFC4 occurrence
    class and does not exist in IFC2X3)."""
    try:
        return list(model.by_type(name))
    except RuntimeError:
        return []


def occurrences_of(model, occ_class, type_class):
    """Find flow-element occurrences across IFC versions.

    IFC4 stores conduit as IfcCableCarrierSegment occurrences directly. IFC2x3
    (Revit's most common export) stores it as a generic occurrence typed by an
    IfcCableCarrierSegmentType. We gather both so the same code reads either.
    """
    items = safe_by_type(model, occ_class)
    have = {x.id() for x in items}
    for rel in safe_by_type(model, "IfcRelDefinesByType"):
        rt = getattr(rel, "RelatingType", None)
        if rt is not None and rt.is_a(type_class):
            for occ in rel.RelatedObjects:
                if occ.id() not in have:
                    have.add(occ.id())
                    items.append(occ)
    return items


# The IfcCableCarrierSegment* family covers round conduit AND flat cable
# trays/ladders/trunking. This bender only bends round conduit, so trays are
# detected and excluded rather than silently turned into (bogus) bend jobs.
CONDUIT_PREDEFINED = {"CONDUITSEGMENT"}
TRAY_PREDEFINED = {"CABLETRAYSEGMENT", "CABLELADDERSEGMENT", "CABLETRUNKINGSEGMENT"}
_TRAY_NAME_HINTS = ("tray", "ladder", "trunking", "cablofil", "kabelrinne", "rinne",
                    "chemin de c", "лоток")  # ...лоток (RU: tray)


def carrier_predefined_type(element):
    """The IfcCableCarrier* PredefinedType, from the occurrence or its defining
    type (covers IFC4 self-typed and IFC2x3 typed-by-relation), or None."""
    pt = getattr(element, "PredefinedType", None)
    if pt:
        return str(pt)
    for rel in (getattr(element, "IsTypedBy", None) or []):
        p = getattr(rel.RelatingType, "PredefinedType", None)
        if p:
            return str(p)
    for rel in (getattr(element, "IsDefinedBy", None) or []):
        if rel.is_a("IfcRelDefinesByType"):
            p = getattr(rel.RelatingType, "PredefinedType", None)
            if p:
                return str(p)
    return None


def is_conduit_segment(element):
    """True if a cable-carrier segment is round conduit (what the bender bends), not
    a cable tray / ladder / trunking. PredefinedType is authoritative; when it's
    absent or USER/NOTDEFINED, fall back to name keywords, else assume conduit — an
    unsized round segment is still caught downstream by the 'unknown size' flag."""
    pt = carrier_predefined_type(element)
    if pt in CONDUIT_PREDEFINED:
        return True
    if pt in TRAY_PREDEFINED:
        return False
    t = ifcopenshell.util.element.get_type(element)
    name = ((getattr(t, "Name", None) or "") + " " + (element.Name or "")).lower()
    if any(h in name for h in _TRAY_NAME_HINTS):
        return False
    return True


def conduit_elements(model):
    """Round-conduit (segments, fittings, n_skipped_carriers) for a model. Cable
    trays/ladders/trunking are excluded here (not fabricable on a conduit bender),
    and their count is returned so the caller can say they were seen and skipped."""
    all_segs = occurrences_of(model, "IfcCableCarrierSegment", "IfcCableCarrierSegmentType")
    segs = [s for s in all_segs if is_conduit_segment(s)]
    fits = occurrences_of(model, "IfcCableCarrierFitting", "IfcCableCarrierFittingType")
    return segs, fits, len(all_segs) - len(segs)


def length_unit_label(model):
    """Short label for the file's length unit (mm / m / FOOT / ...). Real exports
    vary — Revit thinks in feet — so never assume; read it from the file."""
    for u in model.by_type("IfcSIUnit"):
        if u.UnitType == "LENGTHUNIT":
            return {"MILLI": "mm", "CENTI": "cm", "DECI": "dm", None: "m", "": "m"}.get(u.Prefix, f"{u.Prefix} {u.Name}")
    for u in model.by_type("IfcConversionBasedUnit"):
        if u.UnitType == "LENGTHUNIT":
            return u.Name  # e.g. FOOT, INCH
    return "units"


def nominal_diameter(segment):
    psets = ifcopenshell.util.element.get_psets(segment)
    for pset in psets.values():
        for key in ("NominalDiameter", "OuterDiameter", "OverallWidth", "Size"):
            if key in pset:
                return pset[key]
    return None


def outer_diameter(segment):
    """Outer diameter in model units, or None. Tries psets first (a clean
    NominalDiameter etc.), then falls back to the conduit's circular cross-section
    in the geometry (an IfcExtrudedAreaSolid's circle profile), which is where
    Revit actually puts the trade size on these exports."""
    d = nominal_diameter(segment)
    if isinstance(d, (int, float)):
        return float(d)
    rep = getattr(segment, "Representation", None)
    if not rep:
        return None
    for shape in rep.Representations:
        for item in shape.Items:
            if item.is_a("IfcExtrudedAreaSolid"):
                prof = item.SweptArea
                if prof.is_a("IfcCircleProfileDef"):
                    return float(prof.Radius) * 2.0
                if prof.is_a("IfcCircleHollowProfileDef"):
                    return float(prof.OuterRadius) * 2.0
    return None


def conduit_kind(segment):
    """Best-effort conduit material/type label (e.g. 'Electrical Metallic Tubing
    (EMT)') from the element/type name. Revit names look like
    'Conduit with Fittings:Electrical Metallic Tubing (EMT):854413'."""
    t = ifcopenshell.util.element.get_type(segment)
    name = (getattr(t, "Name", None) if t else None) or segment.Name or ""
    parts = [p.strip() for p in name.split(":") if p.strip()]
    return parts[1] if len(parts) >= 2 else (parts[0] if parts else None)


def path_length(verts):
    return sum(norm(sub(verts[i + 1], verts[i])) for i in range(len(verts) - 1))


def group_into_runs(segments, scale=1.0, tol=1.0):
    """Group scattered conduit segments into connected runs.

    Real exports give segments in arbitrary order and as several separate runs,
    NOT one pre-sorted line. This rebuilds the runs from geometry alone: it walks
    each segment's centerline endpoints and stitches together the ones that meet
    (within `tol`), flipping segments as needed, until no more connect -- then
    starts the next run with whatever's left. Returns ordered vertex lists,
    longest run first. (Using the IFC connection ports would be more robust on
    messy exports; shared-endpoint matching is the geometry-only first pass.)
    """
    pieces = []
    for s in segments:
        pts, _ = segment_centerline(s)
        if len(pts) >= 2:
            pieces.append([tuple(c * scale for c in p) for p in pts])

    def close(a, b):
        return norm(sub(a, b)) <= tol

    runs = []
    used = [False] * len(pieces)
    for i in range(len(pieces)):
        if used[i]:
            continue
        used[i] = True
        run = list(pieces[i])
        extended = True
        while extended:
            extended = False
            for j in range(len(pieces)):
                if used[j]:
                    continue
                seg = pieces[j]
                if close(run[-1], seg[0]):
                    run.extend(seg[1:])
                elif close(run[-1], seg[-1]):
                    run.extend(list(reversed(seg))[1:])
                elif close(run[0], seg[-1]):
                    run[:0] = seg[:-1]
                elif close(run[0], seg[0]):
                    run[:0] = list(reversed(seg))[:-1]
                else:
                    continue
                used[j] = True
                extended = True
        # collapse any near-duplicate consecutive points
        cleaned = [run[0]]
        for p in run[1:]:
            if norm(sub(cleaned[-1], p)) > 1e-6:
                cleaned.append(p)
        runs.append(cleaned)

    runs.sort(key=path_length, reverse=True)
    return runs


def port_to_element(model):
    """Map each IfcDistributionPort -> the element it belongs to.

    Revit attaches ports to their host two different ways depending on schema:
    IFC2x3 uses IfcRelConnectsPortToElement; IFC4 nests the ports under the
    element with IfcRelNests. We read both so the same code works either way.
    """
    m = {}
    for rel in safe_by_type(model, "IfcRelConnectsPortToElement"):   # IFC2x3
        port = getattr(rel, "RelatingPort", None)
        el = getattr(rel, "RelatedElement", None)
        if port is not None and el is not None:
            m[port.id()] = el
    for rel in safe_by_type(model, "IfcRelNests"):                   # IFC4
        host = getattr(rel, "RelatingObject", None)
        if host is None:
            continue
        for o in rel.RelatedObjects:
            if o.is_a("IfcDistributionPort"):
                m[o.id()] = host
    return m


def _line_intersection(p1, d1, p2, d2):
    """Midpoint of the closest approach between lines p1+t*d1 and p2+s*d2.

    For two intersecting straights this is their intersection; for skew 3D lines
    it's the nearest meeting point; for (near-)parallel lines it falls back to
    the midpoint of the two base points.
    """
    a, b, c = dot(d1, d1), dot(d1, d2), dot(d2, d2)
    r = sub(p1, p2)
    d, e = dot(d1, r), dot(d2, r)
    denom = a * c - b * b
    if abs(denom) < 1e-9 or a < 1e-12 or c < 1e-12:
        return tuple((p1[i] + p2[i]) / 2.0 for i in range(3))
    t = (b * e - c * d) / denom
    s = (a * e - b * d) / denom
    c1 = tuple(p1[i] + t * d1[i] for i in range(3))
    c2 = tuple(p2[i] + s * d2[i] for i in range(3))
    return tuple((c1[i] + c2[i]) / 2.0 for i in range(3))


def _walk_chain(start, adj, seen):
    """Walk a simple path through the adjacency graph from `start`, marking nodes
    seen. At branches (rare for conduit) it just follows the first option."""
    chain, prev, cur = [], None, start
    while cur is not None and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        nxts = [n for n in adj[cur] if n != prev and n not in seen]
        prev, cur = cur, (nxts[0] if nxts else None)
    return chain


def _min_endpoint_dist(p, piece):
    return min(norm(sub(p, piece[0])), norm(sub(p, piece[-1])))


def _reconstruct_through_pis(pieces):
    """Weave ordered straight pieces into one polyline, putting each bend vertex
    at the intersection (PI) of the two adjacent straights.

    'Conduit without Fittings' trims each straight back by the bend radius, so
    consecutive segments leave a gap the size of the elbow. Naive end-to-end
    stitching would turn each real corner into two false 45-degree kinks across
    that gap. Putting the vertex at the lines' intersection bridges the gap
    cleanly -- which is also the physically correct bend point a bender marks
    (the point of intersection of adjacent straights).
    """
    if len(pieces) == 1:
        return list(pieces[0])
    # orient piece 0 so its head (last point) is the end nearest piece 1
    first, second = pieces[0], pieces[1]
    oriented = [list(first) if _min_endpoint_dist(first[-1], second) <=
                _min_endpoint_dist(first[0], second) else list(reversed(first))]
    # orient each remaining piece so its tail is nearest the previous head
    for k in range(1, len(pieces)):
        prev_head = oriented[-1][-1]
        a, b = pieces[k][0], pieces[k][-1]
        oriented.append(list(pieces[k]) if norm(sub(a, prev_head)) <= norm(sub(b, prev_head))
                        else list(reversed(pieces[k])))
    # weave, replacing each pair of trimmed ends with a single PI vertex
    poly = list(oriented[0])
    for k in range(1, len(oriented)):
        prev, cur = oriented[k - 1], oriented[k]
        pi = _line_intersection(prev[-1], sub(prev[-1], prev[-2]),
                                cur[0], sub(cur[1], cur[0]))
        poly[-1] = pi
        poly.extend(cur[1:])
    return poly


def port_based_runs(model, segments, fittings, scale=1.0, return_segments=False):
    """Group conduit using Revit's exported connection ports (IfcRelConnectsPorts).

    Each segment and elbow carries IfcDistributionPorts wired together by
    IfcRelConnectsPorts, giving the true segment->elbow->segment chain directly.
    That is far more robust than geometric endpoint-matching, because real
    'conduit without fittings' leaves a bend-radius gap between straights and the
    elbow itself can be an unreadable MappedRepresentation. We order the segments
    by ports and take the geometry from the straights only (skipping the elbows),
    so the bend falls out of the direction change between consecutive straights.
    Returns ordered, mm-scaled vertex lists (longest first); [] if the file has
    no usable ports, so the caller falls back to geometric grouping. With
    return_segments=True, returns (vertex_list, [segment_elements]) pairs instead,
    so a caller can read each run's conduit size/type.
    """
    p2e = port_to_element(model)
    if not p2e:
        return []
    elements = list(segments) + list(fittings)
    by_id = {e.id(): e for e in elements}
    seg_ids = {e.id() for e in segments}
    adj = {i: set() for i in by_id}
    for rel in safe_by_type(model, "IfcRelConnectsPorts"):
        a = p2e.get(rel.RelatingPort.id())
        b = p2e.get(rel.RelatedPort.id())
        if a is None or b is None or a.id() == b.id():
            continue
        if a.id() in by_id and b.id() in by_id:
            adj[a.id()].add(b.id())
            adj[b.id()].add(a.id())
    if not any(adj.values()):
        return []  # ports present but none connect our conduit -> use geometry

    seen, chains = set(), []
    for start in adj:                       # start at free ends (degree <= 1)
        if start not in seen and len(adj[start]) <= 1:
            ch = _walk_chain(start, adj, seen)
            if ch:
                chains.append(ch)
    for start in adj:                       # mop up any loops / leftover nodes
        if start not in seen:
            ch = _walk_chain(start, adj, seen)
            if ch:
                chains.append(ch)

    runs = []
    for chain in chains:
        pieces, chain_segs = [], []
        for i in chain:
            if i not in seg_ids:            # use straight-segment geometry only
                continue
            pts, _ = segment_centerline(by_id[i])
            if len(pts) >= 2:
                pieces.append([tuple(c * scale for c in p) for p in pts])
                chain_segs.append(by_id[i])
        if pieces:
            runs.append((_reconstruct_through_pis(pieces), chain_segs))
    runs = [rs for rs in runs if len(rs[0]) >= 2]
    runs.sort(key=lambda rs: path_length(rs[0]), reverse=True)
    if return_segments:
        return runs
    return [poly for poly, _ in runs]


def _run_member_segments(poly, segments, scale, tol=1.0):
    """Best-effort: which segments' centerlines make up a geometry-grouped run,
    so the run can inherit an OD / conduit kind. A run built by group_into_runs
    literally concatenates the segments' own scaled points, so matching on a
    shared centerline point is near-exact."""
    members = []
    for s in segments:
        pts, _ = segment_centerline(s)
        spts = [tuple(c * scale for c in p) for p in pts]
        if any(norm(sub(sp, v)) <= tol for sp in spts for v in poly):
            members.append(s)
    return members


def reconstruct_runs(model, segments, fittings, scale=1.0):
    """Conduit runs as (mm-scaled vertex_list, [member_segments]) pairs.

    Ports first (robust: stitches the segment<->elbow chains); if the file has no
    usable connection ports, fall back to geometric endpoint-grouping so a run is
    still recovered from the raw centerlines. This is the one reconstruction entry
    point every output path (schedule, diagrams, cards) shares, so they all handle
    port-less real-world exports identically instead of silently finding nothing.
    """
    runs = port_based_runs(model, segments, fittings, scale=scale, return_segments=True)
    if runs:
        return runs
    geo = [poly for poly in group_into_runs(list(segments) + list(fittings), scale=scale)
           if len(poly) >= 2]
    return [(poly, _run_member_segments(poly, segments, scale)) for poly in geo]


def _point_line_distance(p, a, b):
    """Perpendicular distance from point p to the line through a and b (3D)."""
    ab = sub(b, a)
    ab_len = norm(ab)
    if ab_len < 1e-12:
        return norm(sub(p, a))
    return norm(cross(sub(p, a), ab)) / ab_len


def simplify_polyline(points, tol):
    """Ramer-Douglas-Peucker simplification.

    Drops points that sit within `tol` of the line through their neighbours, so
    measurement noise and the many short segments of a smooth curve collapse into
    clean straight runs separated by real corners. Without this, derive_bends
    reads every tiny wobble as a bend and a curved run explodes into dozens of
    micro-bends. (A genuine bend *arc* collapses to a single corner here; true
    arc-radius handling is a later refinement.)
    """
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _point_line_distance(points[i], a, b)
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        left = simplify_polyline(points[:idx + 1], tol)
        right = simplify_polyline(points[idx:], tol)
        return left[:-1] + right
    return [a, b]


def derive_bends(verts):
    """Turn a centerline into (advance, rotate, angle) bends.

    advance  = straight feed length leading into the bend
    angle    = turn angle at the corner
    rotate   = change of bend plane vs. the previous bend (0 for the first)
    roll_dir = which way that roll turns: +1 / -1 / 0 (none). The sign is the
        right-hand rule about the feed direction: looking DOWN the conduit as it
        feeds, +1 reads as clockwise, -1 as counter-clockwise. ASSUMPTION — the
        magnitude is exact, but confirm this CW/CCW mapping against the machine's
        ROTATE+ direction; flipping it is a one-line change in roll_dir's sign.
    """
    edges = [sub(verts[i + 1], verts[i]) for i in range(len(verts) - 1)]
    lengths = [norm(e) for e in edges]
    bends = []
    prev_normal = None
    for i in range(1, len(verts) - 1):
        incoming, outgoing = edges[i - 1], edges[i]
        angle = angle_between(incoming, outgoing)
        if angle < STRAIGHT_TOL_DEG:
            continue  # effectively straight, not a bend
        normal = unit(cross(incoming, outgoing))
        rotate, roll_dir = 0.0, 0
        if prev_normal is not None:
            rotate = angle_between(prev_normal, normal)
            # signed about the feed axis (the straight leading into this bend)
            s = dot(cross(prev_normal, normal), unit(incoming))
            roll_dir = 0 if abs(s) < 1e-9 else (1 if s > 0 else -1)
        prev_normal = normal
        bends.append({
            "advance": round(lengths[i - 1], 1),
            "rotate": round(rotate, 1),
            "roll_dir": roll_dir,
            "angle": round(angle, 1),
        })
    tail = lengths[-1] if lengths else 0.0
    return bends, lengths, tail


def snap_to_trade(angle, tol=SNAP_TOL_DEG, rel_tol=SNAP_REL_TOL, force=False):
    """Round a derived angle to the nearest standard trade angle when the change is
    small both in absolute terms (`tol`) AND relative to the angle (`rel_tol`);
    otherwise leave it as-is (a genuinely non-standard bend, reported honestly).
    The relative guard stops a gentle bend like 6° from being forced to 10°.

    `force=True` snaps to the nearest trade angle unconditionally — used to *resolve*
    flagged odd-angle runs when someone opts to standardize them."""
    nearest = min(TRADE_ANGLES, key=lambda t: abs(t - angle))
    if force:
        return nearest
    delta = abs(nearest - angle)
    return nearest if (delta <= tol and delta <= rel_tol * angle) else angle


def snap_roll(rotate, tol=ROLL_SNAP_TOL_DEG):
    """Snap a roll (bend-plane change) to the nearest right angle (0/90/180)
    within `tol`. Orthogonal building conduit rolls are all multiples of 90°, but
    reconstruction leaves them a degree or two off; this cleans that noise. A
    genuinely diagonal roll (a true saddle, angled routing) falls outside `tol`
    and is left as-is."""
    nearest = min(ROLL_ANGLES, key=lambda t: abs(t - rotate))
    return nearest if abs(nearest - rotate) <= tol else rotate


def drop_near_straight(verts, min_deg=MIN_BEND_DEG):
    """Remove interior vertices whose turn is gentler than `min_deg`, merging the
    adjacent straights into one.

    Real conduit picks up sub-degree-to-few-degree kinks from routing slack and
    from reconstructing the elbow's bend point; those aren't bends the machine
    should make. Dropping the vertex (rather than just zeroing the angle)
    correctly merges the straight, so the surrounding advances and roll angles
    re-derive consistently.
    """
    if len(verts) <= 2:
        return list(verts)
    out = [verts[0]]
    for i in range(1, len(verts) - 1):
        incoming = sub(verts[i], out[-1])
        outgoing = sub(verts[i + 1], verts[i])
        if angle_between(incoming, outgoing) >= min_deg:
            out.append(verts[i])
    out.append(verts[-1])
    return out


def split_into_pieces(bends, tail, stick_mm=STICK_MM, clearance_mm=COUPLER_CLEARANCE_MM,
                       radius_mm=0.0):
    """Split one run into physical conduit pieces (sticks).

    Conduit comes in `stick_mm` lengths and is bent one stick at a time, then
    coupled. Couplers may only go in a STRAIGHT segment, at least `clearance_mm`
    from any bend. This walks the run and places couplers (cuts) so every piece
    is <= one stick, cutting as late as possible (fewest couplers).

    `bends` is derive_bends' output (each carries 'advance' = straight before it);
    `tail` is the straight after the last bend. Returns (pieces, warnings); each
    piece is {length_mm, developed_mm, bends:[{feed, angle, rotate, arc_mm,
    takeup_mm}], tail_mm, start_coupler, end_coupler}.

    When `radius_mm` > 0 the feeds/tail carry the take-up (deduct) correction for
    that bend-shoe radius (see bend_radius_mm): each feed is shortened by the
    set-back  R*tan(angle/2)  at every bend-adjacent end (never at a cut/run end,
    which is a straight), and `developed_mm` is the real cut length (corrected
    straights + R*angle arcs). With radius_mm == 0 it stays sharp-corner geometry.
    Cuts are still placed on the sharp-corner walk, which only over-reserves (the
    developed length is always <= it), so a stick never runs short of material.
    """
    def setback(angle):
        return radius_mm * math.tan(math.radians(angle) / 2.0) if radius_mm else 0.0

    def arc(angle):
        return radius_mm * math.radians(angle) if radius_mm else 0.0
    advances = [b["advance"] for b in bends]
    bend_pos, p = [], 0.0
    for a in advances:
        p += a
        bend_pos.append(p)                      # each bend's position along the run
    total = (bend_pos[-1] if bend_pos else 0.0) + tail

    # the cuttable sub-interval of every straight (incl. the tail), trimmed by clearance
    straights, prev = [], 0.0
    for bp in bend_pos:
        straights.append((prev, bp))
        prev = bp
    straights.append((prev, total))
    cuttable = [(s + clearance_mm, e - clearance_mm) for s, e in straights
                if e - s >= 2 * clearance_mm]

    def latest_cut(limit, after):
        """largest valid coupler position in (after, limit]."""
        best = None
        for lo, hi in cuttable:
            if hi <= after or lo > limit:
                continue
            c = min(hi, limit)
            if c > after and (best is None or c > best):
                best = c
        return best

    cuts, start, warnings = [], 0.0, []
    while total - start > stick_mm + 1e-6:
        c = latest_cut(start + stick_mm, start)
        if c is None:
            warnings.append(f"no coupler spot within {stick_mm / 304.8:.0f} ft after "
                            f"{start / 304.8:.1f} ft (bends too close / straights too short)")
            break
        cuts.append(c)
        start = c

    bounds = [0.0] + cuts + [total]
    pieces = []
    for i in range(len(bounds) - 1):
        ps, pe = bounds[i], bounds[i + 1]
        # last = position of the previous mark; prev_set = set-back already spent at it
        # (0 at a cut/run end — that's a straight — else the previous bend's take-up).
        pb, last, prev_set, dev = [], ps, 0.0, 0.0
        for b, bp in zip(bends, bend_pos):
            if ps < bp < pe:
                s = setback(b["angle"])
                feed = round((bp - last) - prev_set - s, 1)
                pb.append({"feed": feed, "angle": b["angle"], "rotate": b["rotate"],
                           "roll_dir": b.get("roll_dir", 0),
                           "arc_mm": round(arc(b["angle"]), 1),
                           "takeup_mm": round(s, 1)})
                dev += max(feed, 0.0) + arc(b["angle"])
                last, prev_set = bp, s
        tail_mm = round((pe - last) - prev_set, 1)
        dev += max(tail_mm, 0.0)
        pieces.append({
            "length_mm": round(pe - ps, 1),        # span along the route (sharp-corner)
            "developed_mm": round(dev, 1),         # material to cut (straights + arcs)
            "bends": pb,
            "tail_mm": tail_mm,
            "start_coupler": i > 0,                 # interior end -> coupled
            "end_coupler": i < len(bounds) - 2,
        })
    return pieces, warnings


def pack_labeled(items, stick_mm=STICK_MM):
    """First-Fit-Decreasing bin-packing of (label, length_mm) items into raw
    `stick_mm` sticks. Short (partial) pieces nest into the offcut of a longer
    one. Pack per conduit SIZE (different stock can't share). Returns a list of
    sticks, each a list of the (label, length) pieces cut from it (longest first)."""
    caps, sticks = [], []                        # remaining capacity / contents per stick
    for label, L in sorted(items, key=lambda t: t[1], reverse=True):
        L = min(L, stick_mm)
        for j in range(len(caps)):
            if caps[j] + 1e-6 >= L:
                caps[j] -= L
                sticks[j].append((label, L))
                break
        else:
            caps.append(stick_mm - L)
            sticks.append([(label, L)])
    return sticks


def pack_sticks(lengths, stick_mm=STICK_MM):
    """How many raw sticks the cut-lengths need (offcut-optimized); see
    pack_labeled. Returns a list of sticks, each a list of cut-lengths."""
    packed = pack_labeled(list(enumerate(lengths)), stick_mm)
    return [[L for _, L in stick] for stick in packed]


# Trade operations are named multi-bend moves an electrician thinks in. Roll here
# is derive_bends' `rotate` (plane change vs. the previous bend): 180° means the
# next bend is coplanar but turns the opposite way.
OP_ANGLE_TOL = 0.6      # two bend angles counted "equal" within this (deg)
OP_ROLL_TOL = 2.0       # a roll counted as a 180° flip within this (deg)
OFFSET_MAX_ANGLE = 89.0  # an offset uses an offset-range angle; a 90° pair is
                         # routing/corners (go up, travel, come back), not an offset
OFFSET_MAX_SPAN = STICK_MM  # an offset is fabricated on one stick; bends farther
                            # apart than this are just two separate bends


def _flip(rotate):
    return abs(rotate - 180.0) <= OP_ROLL_TOL


def classify_ops(bends, span_key="advance"):
    """Group a run's bends into named trade operations (following the Mike Holt
    round-raceway vocabulary). Returns a list of ops in run order; each op is
    {type, idx:[bend indices], angle, ...}:

      - 'offset' — two EQUAL offset-range bends (< 90°, within one stick) with the
        second rolled 180° (coplanar, opposite way): the conduit steps sideways and
        runs parallel again. Carries rise_mm = center-to-center * sin(angle) (the
        lateral shift). A 90° pair or a far-apart pair is routing, left as bends.
      - 'saddle' — a 3-point saddle over an obstruction: angles theta, 2*theta,
        theta, the 2nd and 3rd rolled 180°.
      - 'bend'   — a single bend that isn't part of an offset/saddle (a 90° stub,
        a corner, a kick).

    Detection is on the sharp-corner bends (roll/angle), independent of stick
    cuts; a 180° flip + equal angle IS an offset geometrically, so it's reliable.
    `span_key` is the field holding the straight length before each bend — use the
    default "advance" for a run's bends, or "feed" for a single stick's bends (so
    an offset split across a coupler naturally falls back to two separate bends).
    """
    n = len(bends)
    ops, i = [], 0
    while i < n:
        a = bends[i]["angle"]
        # 3-point saddle: theta, 2*theta, theta with the middle & last flipped
        if (i + 2 < n
                and abs(bends[i + 2]["angle"] - a) <= OP_ANGLE_TOL
                and abs(bends[i + 1]["angle"] - 2 * a) <= OP_ANGLE_TOL
                and _flip(bends[i + 1]["rotate"]) and _flip(bends[i + 2]["rotate"])):
            # 3-point saddle: side bends theta, center 2*theta. Rise (obstruction
            # height) = distance to the center bend * sin(theta); the mark spacing
            # from the center to each side bend is rise * cot(theta) (the classic
            # saddle multiplier: a 45deg center saddle -> ~2.5x).
            span_c = bends[i + 1].get(span_key, 0.0)
            rise = span_c * math.sin(math.radians(a))
            ops.append({"type": "saddle", "idx": [i, i + 1, i + 2], "angle": a,
                        "center_angle": round(2 * a, 1),
                        "rise_mm": round(rise, 1),
                        "multiplier": round(1.0 / math.tan(math.radians(a)), 2)})
            i += 3
            continue
        # offset: two equal offset-range bends, second flipped 180°, on one stick
        span = bends[i + 1].get(span_key, 0.0) if i + 1 < n else 0.0
        if (i + 1 < n and abs(bends[i + 1]["angle"] - a) <= OP_ANGLE_TOL
                and _flip(bends[i + 1]["rotate"])
                and a < OFFSET_MAX_ANGLE
                and span <= OFFSET_MAX_SPAN):
            # Mike Holt offset math: rise is the lateral shift; shrink is the
            # run-length the offset "eats" (= rise * tan(angle/2)); multiplier is
            # the classic mark-spacing factor (= 1/sin(angle): 30°->2, 45°->1.4).
            rise = span * math.sin(math.radians(a))
            ops.append({"type": "offset", "idx": [i, i + 1], "angle": a,
                        "rise_mm": round(rise, 1),
                        "shrink_mm": round(rise * math.tan(math.radians(a) / 2.0), 1),
                        "multiplier": round(1.0 / math.sin(math.radians(a)), 2)})
            i += 2
            continue
        ops.append({"type": "bend", "idx": [i], "angle": a})
        i += 1
    return ops


def rule(c="-", w=66):
    print(c * w)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IFC
    model = ifcopenshell.open(path)

    rule("=")
    print("IFC CONDUIT EXTRACTION  ->  BEND JOB")
    rule("=")
    unit = length_unit_label(model)
    try:
        mm_scale = ifcopenshell.util.unit.calculate_unit_scale(model) * 1000.0
    except Exception:
        mm_scale = 1.0
    print(f"  File:   {path}")
    print(f"  Schema: {model.schema}")
    print(f"  Units:  source = {unit}; all lengths below normalized to mm")
    print()

    segments, fittings, n_trays = conduit_elements(model)
    if n_trays:
        print(f"  (skipped {n_trays} cable tray/ladder/trunking carrier(s) — "
              f"not round conduit, not bendable here)")
    port_runs = port_based_runs(model, segments, fittings, scale=mm_scale)
    use_ports = bool(port_runs)
    print(f"Found {len(segments)} conduit segment(s), {len(fittings)} fitting(s):")
    usable = 0
    ods, kinds = [], []
    for s in segments:
        pts, source = segment_centerline(s)
        if pts:
            usable += 1
        pts = [tuple(c * mm_scale for c in p) for p in pts]
        od = outer_diameter(s)
        kind = conduit_kind(s)
        if od:
            ods.append(round(od * mm_scale, 1))
        if kind:
            kinds.append(kind)
        dia_txt = f"OD {od * mm_scale:g} mm" if isinstance(od, (int, float)) else "?"
        span = norm(sub(pts[-1], pts[0])) if len(pts) >= 2 else 0.0
        name = s.Name or f"#{s.id()}"
        print(f"  - {name}")
        print(f"      geometry: {source} | {dia_txt} | span {span:g} mm")
    dom_od = max(set(ods), key=ods.count) if ods else None
    dom_kind = max(set(kinds), key=kinds.count) if kinds else None
    if dom_od or dom_kind:
        print(f"  conduit: {dom_kind or '?'}, outer diameter {dom_od or '?'} mm "
              f"(drives die / bend radius — not yet mapped)")
    print()
    print(f"{usable}/{len(segments)} segment(s) yielded a usable centerline.")
    if fittings:
        if use_ports:
            print("NOTE: connectivity comes from the IFC ports; the elbow fittings "
                  "mark the bends, so their geometry isn't needed.")
        else:
            print(f"NOTE: {len(fittings)} fitting(s) folded into run-grouping — a bend "
                  f"at an elbow comes through from the stitched geometry.")
    print()

    if use_ports:
        runs = [r for r in port_runs if len(r) >= 2]
        grouping = "IFC connection ports (segment <-> elbow chain)"
    else:
        runs = [r for r in group_into_runs(segments + fittings, scale=mm_scale) if len(r) >= 2]
        grouping = "shared endpoints (geometry)"
    if not runs:
        print("No usable centerline found; cannot derive bends.")
        return
    print(f"Grouped {len(segments)} segment(s) + {len(fittings)} fitting(s) into "
          f"{len(runs)} connected run(s) via {grouping}:")
    print()

    jobs = []  # (run_index, bends) for runs that actually bend
    for idx, run in enumerate(runs, 1):
        simplified = simplify_polyline(run, SIMPLIFY_TOL)
        cleaned = drop_near_straight(simplified, MIN_BEND_DEG)
        bends, lengths, tail = derive_bends(cleaned)
        for b in bends:                       # snap to the trade angles / right-angle rolls
            b["angle"] = round(snap_to_trade(b["angle"]), 1)
            b["rotate"] = round(snap_roll(b["rotate"]), 1)
        note = (f" -> {len(cleaned)} after simplify+clean"
                if len(cleaned) != len(run) else "")
        print(f"Run {idx}: {len(run)} points{note}, length {sum(lengths):g} mm, "
              f"{len(bends)} bend(s)")
        if bends:
            print(f"    {'#':>2}  {'ADVANCE':>9}  {'ROTATE':>8}  {'ANGLE':>8}")
            for i, b in enumerate(bends, 1):
                print(f"    {i:>2}  {b['advance']:>9g}  {b['rotate']:>8g}  {b['angle']:>8g}")
            jobs.append((idx, bends))
        else:
            print("    (straight run — no bends)")
    print()

    if not jobs:
        print("Conduit found, but no bends in any run (straight / single-segment).")
        return

    # runs are sorted longest-first, so jobs[0] is the longest bending run
    job_idx, job_bends = jobs[0]
    job = {
        "name": f"Derived from {os.path.basename(path)} (run {job_idx} of {len(runs)})",
        "description": "Auto-derived from IFC conduit centerline. First pass, "
                       "uncalibrated, not hardware-reviewed.",
        "units": "millimetres of centerline / degrees of turn - NOT yet converted to motor steps",
        "conduit": dom_kind or "unknown",
        "outer_diameter_mm": dom_od,
        "bends": job_bends,
    }
    with open(OUT_JOB, "w") as fh:
        json.dump(job, fh, indent=2)
    print(f"Wrote longest run ({len(job_bends)} bends) to {OUT_JOB}")
    print(f"  Run it through the simulator:  python3 run_demo.py {OUT_JOB}")
    print()

    rule()
    print("Honest caveats (say these to the team):")
    if use_ports:
        print("  * Runs are ordered from the IFC connection ports (robust); each bend")
        print("    is taken from the direction change between consecutive straights,")
        print("    with the vertex at their intersection (the bend point of the elbow).")
    else:
        print("  * Runs are rebuilt from shared endpoints (geometry only); using the")
        print("    IFC connection ports would be more robust on messy real exports.")
    print("  * Angles are snapped to the standard trade set (10/22.5/30/45/60/90),")
    print("    and kinks gentler than 5° are dropped as routing slack (not bends).")
    print("  * 'rotate' is the bend-plane change, snapped to right angles when")
    print("    near one; its direction (CW/CCW) and springback are still TODO.")
    print("  * Lengths are normalized to mm but NOT calibrated to motor units")
    print("    (degrees/mm -> motor steps conversion is still TODO).")
    print("  * Fittings are stitched into runs by geometry; reading a fitting's")
    print("    explicit Angle property (vs deriving it) is a future refinement.")
    print("  * Tessellated-mesh geometry has no centerline and is skipped.")


if __name__ == "__main__":
    main()
