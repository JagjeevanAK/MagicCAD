# SPDX-License-Identifier: LGPL-2.1-or-later

import traceback

import FreeCAD


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
    import InvoluteGearFeature

    name = op.get("name", "InvoluteGear")
    profile_name = op.get("profile_name", "{0}Profile".format(name))
    thickness = float(op.get("thickness", 0.0) or 0.0)
    bore = float(op.get("center_bore", 0.0) or 0.0)

    profile = InvoluteGearFeature.makeInvoluteGear(profile_name)
    if "number_of_teeth" in op:
        profile.NumberOfTeeth = int(op["number_of_teeth"])
    if "module" in op:
        profile.Modules = _coerce_quantity(op["module"], "mm")
    if "pressure_angle" in op:
        profile.PressureAngle = _coerce_quantity(op["pressure_angle"], "deg")
    if "external_gear" in op:
        profile.ExternalGear = bool(op["external_gear"])

    created = [profile.Name]
    result = profile
    if thickness > 0.0:
        extrusion = document.addObject("Part::Extrusion", name)
        extrusion.Base = profile
        extrusion.Dir = FreeCAD.Vector(0, 0, thickness)
        extrusion.Solid = True
        created.append(extrusion.Name)
        result = extrusion
        try:
            profile.ViewObject.Visibility = False
        except Exception:
            pass

        if bore > 0.0:
            cylinder = document.addObject("Part::Cylinder", "{0}Bore".format(name))
            cylinder.Radius = bore / 2.0
            cylinder.Height = thickness
            cut = document.addObject("Part::Cut", "{0}Solid".format(name))
            cut.Base = extrusion
            cut.Tool = cylinder
            created.extend([cylinder.Name, cut.Name])
            result = cut
            try:
                extrusion.ViewObject.Visibility = False
                cylinder.ViewObject.Visibility = False
            except Exception:
                pass

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
