"""Generate a tiny sample conduit IFC so we can develop IFC extraction without
waiting on a real BIM export from the company.

This is the BIM-side equivalent of SimMachine: a stand-in input so the pipeline
can be built and tested end to end today. Swap in a real IFC export later --
the extractor (extract_conduit.py) doesn't care where the file came from.

The model is one conduit run shaped like an offset: three straight
IfcCableCarrierSegment pieces (CONDUITSEGMENT) meeting at two 45-degree bends,
each carrying its centerline as an 'Axis' polyline -- the same thing a real
Revit export gives us to derive bends from.

    python3 bim/make_sample_ifc.py            # writes bim/sample_conduit.ifc
"""

import os
import ifcopenshell

OUT = os.path.join(os.path.dirname(__file__), "sample_conduit.ifc")

# Conduit run centerline, in millimetres. Each tuple is one straight segment
# (start, end). The run goes +X, kinks up 45 deg, then back to +X: an offset.
SEGMENTS = [
    ((0.0, 0.0, 0.0), (500.0, 0.0, 0.0)),
    ((500.0, 0.0, 0.0), (700.0, 200.0, 0.0)),
    ((700.0, 200.0, 0.0), (1200.0, 200.0, 0.0)),
]
NOMINAL_DIAMETER_MM = 20.0  # 3/4" EMT, roughly


def main():
    f = ifcopenshell.file(schema="IFC4")

    # --- units: millimetres ---
    mm = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    units = f.create_entity("IfcUnitAssignment", Units=[mm])

    # --- geometric context + an 'Axis' subcontext for centerlines ---
    origin = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    world = f.create_entity("IfcAxis2Placement3D", Location=origin)
    ctx = f.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=world,
    )
    axis_ctx = f.create_entity(
        "IfcGeometricRepresentationSubContext",
        ContextIdentifier="Axis",
        ContextType="Model",
        ParentContext=ctx,
        TargetView="GRAPH_VIEW",
    )

    # --- project + spatial tree (site > building > storey) ---
    project = f.create_entity(
        "IfcProject",
        GlobalId=ifcopenshell.guid.new(),
        Name="Tubender Sample Conduit",
        RepresentationContexts=[ctx],
        UnitsInContext=units,
    )
    site = f.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site", CompositionType="ELEMENT")
    building = f.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="Building", CompositionType="ELEMENT")
    storey = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Level 1", CompositionType="ELEMENT")
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=project, RelatedObjects=[site])
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=site, RelatedObjects=[building])
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=building, RelatedObjects=[storey])

    placement = f.create_entity("IfcLocalPlacement", RelativePlacement=world)

    segments = []
    for i, (start, end) in enumerate(SEGMENTS, 1):
        p0 = f.create_entity("IfcCartesianPoint", Coordinates=start)
        p1 = f.create_entity("IfcCartesianPoint", Coordinates=end)
        polyline = f.create_entity("IfcPolyline", Points=[p0, p1])
        shape = f.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=axis_ctx,
            RepresentationIdentifier="Axis",
            RepresentationType="Curve3D",
            Items=[polyline],
        )
        product_shape = f.create_entity("IfcProductDefinitionShape", Representations=[shape])
        seg = f.create_entity(
            "IfcCableCarrierSegment",
            GlobalId=ifcopenshell.guid.new(),
            Name=f"Conduit Run 1 - segment {i}",
            ObjectPlacement=placement,
            Representation=product_shape,
            PredefinedType="CONDUITSEGMENT",
        )
        segments.append(seg)

        # one property set carrying the nominal diameter, like a real export
        prop = f.create_entity(
            "IfcPropertySingleValue",
            Name="NominalDiameter",
            NominalValue=f.create_entity("IfcPositiveLengthMeasure", NOMINAL_DIAMETER_MM),
        )
        pset = f.create_entity(
            "IfcPropertySet",
            GlobalId=ifcopenshell.guid.new(),
            Name="Pset_ConduitDemo",
            HasProperties=[prop],
        )
        f.create_entity(
            "IfcRelDefinesByProperties",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=[seg],
            RelatingPropertyDefinition=pset,
        )

    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=ifcopenshell.guid.new(),
        RelatingStructure=storey,
        RelatedElements=segments,
    )

    f.write(OUT)
    print(f"Wrote {OUT}")
    print(f"  {len(segments)} IfcCableCarrierSegment (conduit) pieces, units = mm")


if __name__ == "__main__":
    main()
