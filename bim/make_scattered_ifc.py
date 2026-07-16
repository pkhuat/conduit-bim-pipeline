"""Generate a deliberately MESSY conduit IFC to test run-grouping.

Unlike make_sample_ifc.py (one tidy in-order run), this writes TWO separate
runs whose segments are listed OUT OF ORDER -- which is how real exports arrive.
It's the test fixture for the connectivity logic in extract_conduit.py
(group_into_runs): the extractor should rebuild both runs from the geometry and
derive the right bends, regardless of the order the segments appear.

    Run A : an L  -> one 90-degree bend
    Run B : an offset -> two 45-degree bends

    python3 bim/make_scattered_ifc.py     # writes bim/scattered_conduit.ifc
"""

import os
import ifcopenshell

OUT = os.path.join(os.path.dirname(__file__), "scattered_conduit.ifc")

# (start, end, run-label) in mm. Listed SHUFFLED on purpose -- not run order.
SEGMENTS = [
    ((300.0, 1000.0, 0.0), (450.0, 1150.0, 0.0), "B"),   # B middle
    ((400.0, 0.0, 0.0),    (400.0, 300.0, 0.0),  "A"),   # A second leg
    ((450.0, 1150.0, 0.0), (750.0, 1150.0, 0.0), "B"),   # B end
    ((0.0, 0.0, 0.0),      (400.0, 0.0, 0.0),    "A"),   # A first leg
    ((0.0, 1000.0, 0.0),   (300.0, 1000.0, 0.0), "B"),   # B start
]


def main():
    f = ifcopenshell.file(schema="IFC4")

    mm = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    units = f.create_entity("IfcUnitAssignment", Units=[mm])
    origin = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    world = f.create_entity("IfcAxis2Placement3D", Location=origin)
    ctx = f.create_entity("IfcGeometricRepresentationContext", ContextType="Model",
                          CoordinateSpaceDimension=3, Precision=1e-5, WorldCoordinateSystem=world)
    axis_ctx = f.create_entity("IfcGeometricRepresentationSubContext", ContextIdentifier="Axis",
                               ContextType="Model", ParentContext=ctx, TargetView="GRAPH_VIEW")
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(),
                              Name="Tubender Scattered Conduit", RepresentationContexts=[ctx],
                              UnitsInContext=units)
    storey = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(),
                             Name="Level 1", CompositionType="ELEMENT")
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                    RelatingObject=project, RelatedObjects=[storey])
    placement = f.create_entity("IfcLocalPlacement", RelativePlacement=world)

    segments = []
    for i, (start, end, run) in enumerate(SEGMENTS, 1):
        p0 = f.create_entity("IfcCartesianPoint", Coordinates=start)
        p1 = f.create_entity("IfcCartesianPoint", Coordinates=end)
        polyline = f.create_entity("IfcPolyline", Points=[p0, p1])
        shape = f.create_entity("IfcShapeRepresentation", ContextOfItems=axis_ctx,
                                RepresentationIdentifier="Axis", RepresentationType="Curve3D",
                                Items=[polyline])
        prod = f.create_entity("IfcProductDefinitionShape", Representations=[shape])
        seg = f.create_entity("IfcCableCarrierSegment", GlobalId=ifcopenshell.guid.new(),
                              Name=f"Run {run} - piece {i} (scattered)", ObjectPlacement=placement,
                              Representation=prod, PredefinedType="CONDUITSEGMENT")
        segments.append(seg)

    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                    RelatingStructure=storey, RelatedElements=segments)

    f.write(OUT)
    print(f"Wrote {OUT}")
    print(f"  {len(segments)} segments (shuffled) across 2 runs: A (90 bend), B (two 45 bends)")


if __name__ == "__main__":
    main()
