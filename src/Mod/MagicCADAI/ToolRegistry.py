# SPDX-License-Identifier: LGPL-2.1-or-later

import traceback

import FreeCAD
import Part


def _document(document=None):
    return document or FreeCAD.ActiveDocument


def _success(**payload):
    payload["ok"] = True
    return payload


def _failure(message, **payload):
    payload["ok"] = False
    payload["error"] = message
    return payload


def _coerce_quantity(value, unit_suffix):
    if isinstance(value, (int, float)):
        return "{0} {1}".format(value, unit_suffix)
    return value


def get_object_details(document=None, object_name=""):
    import Snapshot

    document = _document(document)
    if document is None:
        return _failure("No active document")
    obj = document.getObject(object_name)
    if obj is None:
        return _failure("Object '{0}' was not found".format(object_name))
    return _success(object=Snapshot.summarize_object(obj))


def _create_involute_gear(document, op):
    from fcgear import fcgear, involute

    name = op.get("name", "InvoluteGear")
    thickness = float(op.get("thickness", 0.0) or 0.0)
    bore = float(op.get("center_bore", 0.0) or 0.0)
    module = float(op.get("module", 2.0) or 2.0)
    teeth = int(op.get("number_of_teeth", 10) or 10)
    pressure_angle = float(op.get("pressure_angle", 20.0) or 20.0)
    external_gear = bool(op.get("external_gear", True))
    addendum = float(op.get("addendum_coefficient", 1.0 if external_gear else 0.6) or (1.0 if external_gear else 0.6))
    dedendum = float(op.get("dedendum_coefficient", 1.25) or 1.25)
    fillet = float(op.get("root_fillet_coefficient", 0.38) or 0.38)
    shift = float(op.get("profile_shift_coefficient", 0.0) or 0.0)

    wire_builder = fcgear.FCWireBuilder()
    generator = involute.CreateExternalGear if external_gear else involute.CreateInternalGear
    generator(
        wire_builder,
        module,
        teeth,
        pressure_angle,
        split=True,
        addCoeff=addendum,
        dedCoeff=dedendum,
        filletCoeff=fillet,
        shiftCoeff=shift,
    )
    gear_wire = Part.Wire([segment.toShape() for segment in wire_builder.wire])
    base_shape = Part.Face(gear_wire)

    created = []
    result = None
    if thickness > 0.0:
        solid_shape = base_shape.extrude(FreeCAD.Vector(0, 0, thickness))
        if bore > 0.0:
            solid_shape = solid_shape.cut(Part.makeCylinder(bore / 2.0, thickness))
        solid = Part.show(solid_shape, name)
        created.append(solid.Name)
        result = solid
    else:
        profile = Part.show(gear_wire, name)
        created.append(profile.Name)
        result = profile

    return _success(created=created, result_object=result.Name)


def _create_body(document, op):
    name = op.get("name", "Body")
    body = document.addObject("PartDesign::Body", name)
    return _success(created=[body.Name], result_object=body.Name)


def _rename_object(document, op):
    object_name = op.get("object_name", "")
    new_label = op.get("new_label", "")
    obj = document.getObject(object_name)
    if obj is None:
        return _failure("Object '{0}' was not found".format(object_name))
    obj.Label = new_label
    return _success(updated=[obj.Name], result_object=obj.Name)


def _set_parameter(document, op):
    object_name = op.get("object_name", "")
    property_name = op.get("property_name", "")
    value = op.get("value")
    obj = document.getObject(object_name)
    if obj is None:
        return _failure("Object '{0}' was not found".format(object_name))
    try:
        setattr(obj, property_name, value)
    except Exception as exc:
        return _failure("Failed to set {0}.{1}: {2}".format(object_name, property_name, exc))
    return _success(updated=[obj.Name], result_object=obj.Name)


def _recompute(document, op):
    document.recompute()
    return _success(result_object=document.Name)


def _apply_operation(document, op):
    op_name = op.get("op", "")
    if op_name == "create_involute_gear":
        return _create_involute_gear(document, op)
    if op_name == "create_body":
        return _create_body(document, op)
    if op_name == "rename_object":
        return _rename_object(document, op)
    if op_name == "set_parameter":
        return _set_parameter(document, op)
    if op_name == "recompute":
        return _recompute(document, op)
    return _failure("Unsupported operation '{0}'".format(op_name))


def apply_ops(ops, document=None, transaction_name="MagicCAD AI Draft"):
    document = _document(document)
    if document is None:
        return _failure("No active document")

    results = []
    document.openTransaction(transaction_name)
    try:
        for op in ops:
            result = _apply_operation(document, op)
            results.append({"op": op, "result": result})
            if not result.get("ok", False):
                raise RuntimeError(result.get("error", "Operation failed"))
        document.recompute()
        document.commitTransaction()
        return _success(results=results)
    except Exception as exc:
        document.abortTransaction()
        return _failure(str(exc), results=results, traceback=traceback.format_exc())


def execute_tool_request(tool_request, document=None):
    tool_name = tool_request.get("tool_name", "")
    arguments = tool_request.get("arguments", {})
    if tool_name == "get_object_details":
        return get_object_details(document=document, object_name=arguments.get("object_name", ""))
    if tool_name == "get_document_snapshot":
        import Snapshot

        return _success(snapshot=Snapshot.build_document_snapshot(document=document, selection_only=arguments.get("selection_only", False)))
    if tool_name == "apply_ops":
        return apply_ops(arguments.get("ops", []), document=document)
    return _failure("Unsupported tool request '{0}'".format(tool_name))
