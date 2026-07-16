"""Generate a conduit run whose two straight segments connect ONLY through a
fitting (elbow) -- to test fitting-aware run-grouping.

Revit's "conduit with fittings" mode puts the bend in a separate
IfcCableCarrierFitting between straight segments. So the two segments here do
NOT share an endpoint; only the fitting bridges them. Without fitting handling
the extractor sees two disconnected runs and no bend; with it, the chain
segment -> fitting -> segment stitches into one run and the 90-degree bend
falls out of the geometry.

    Segment A : (0,0,0) -> (400,0,0)      [+X]
    Fitting   : (400,0,0) -> (400,100,0)  [the elbow, turning +Y]
    Segment B : (400,100,0) -> (400,400,0) [+Y]

    python3 bim/make_fitting_ifc.py     # writes bim/fitting_conduit.ifc
"""

import os
import ifcopenshell

OUT = os.path.join(os.path.dirname(__file__), "fitting_conduit.ifc")

# (start, end, ifc_class) -- listed shuffled, segments and the fitting mixed.
PIECES = [
    ((400.0, 100.0, 0.0), (400.0, 400.0, 0.0), "IfcCableCarrierSegment"),  # B
    ((400.0, 0.0, 0.0),   (400.0, 100.0, 0.0), "IfcCableCarrierFitting"),  # elbow
    ((0.0, 0.0, 0.0),     (400.0, 0.0, 0.0),   "IfcCableCarrierSegment"),  # A
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
                              Name="Tubender Fitting Conduit", RepresentationContexts=[ctx],
                              UnitsInContext=units)
    storey = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(),
                             Name="Level 1", CompositionType="ELEMENT")
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                    RelatingObject=project, RelatedObjects=[storey])
    placement = f.create_entity("IfcLocalPlacement", RelativePlacement=world)

    elements = []
    for i, (start, end, cls) in enumerate(PIECES, 1):
        p0 = f.create_entity("IfcCartesianPoint", Coordinates=start)
        p1 = f.create_entity("IfcCartesianPoint", Coordinates=end)
        polyline = f.create_entity("IfcPolyline", Points=[p0, p1])
        shape = f.create_entity("IfcShapeRepresentation", ContextOfItems=axis_ctx,
                                RepresentationIdentifier="Axis", RepresentationType="Curve3D",
                                Items=[polyline])
        prod = f.create_entity("IfcProductDefinitionShape", Representations=[shape])
        kind = "fitting" if cls.endswith("Fitting") else "segment"
        el = f.create_entity(cls, GlobalId=ifcopenshell.guid.new(),
                             Name=f"Run 1 - {kind} {i}", ObjectPlacement=placement,
                             Representation=prod)
        elements.append(el)

    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                    RelatingStructure=storey, RelatedElements=elements)
    f.write(OUT)
    print(f"Wrote {OUT}")
    print("  2 segments + 1 fitting (shuffled); segments connect only via the fitting")


if __name__ == "__main__":
    main()
