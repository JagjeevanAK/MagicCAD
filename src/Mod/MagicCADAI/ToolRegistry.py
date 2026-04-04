# SPDX-License-Identifier: LGPL-2.1-or-later

import datetime
import json
import os
import traceback

import FreeCAD
import Part


def _project_root():
    current = os.path.abspath(os.path.dirname(__file__))
    while current and current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, "pixi.toml")):
            return current
        current = os.path.dirname(current)
    return os.path.abspath(os.getcwd())


def _log(message, **payload):
    try:
        line = "{0} INFO [ToolRegistry] {1}".format(
            datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            message,
        )
        if payload:
            line += " | " + json.dumps(payload, sort_keys=True, default=str)
        with open(os.path.join(_project_root(), "magiccadai.log"), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def _style_created_object(obj):
    if obj is None or not FreeCAD.GuiUp:
        return
    # Force FreeCAD to evaluate the shape and generate visualization nodes
    try:
        obj.purgeTouched()
    except Exception:
        pass
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    try:
        if hasattr(view, "show"):
            view.show()
        view.Visibility = True
    except Exception:
        pass
    try:
        if hasattr(view, "DisplayMode"):
            mode_names = []
            if hasattr(view, "listDisplayModes"):
                mode_names = list(view.listDisplayModes())
            preferred = "Shaded" if "Shaded" in mode_names else ("Flat Lines" if "Flat Lines" in mode_names else "")
            if preferred:
                view.DisplayMode = preferred
    except Exception:
        pass
    try:
        if hasattr(view, "ShapeColor"):
            view.ShapeColor = (0.78, 0.82, 0.88)
    except Exception:
        pass
    try:
        if hasattr(view, "LineColor"):
            view.LineColor = (0.18, 0.55, 0.95)
    except Exception:
        pass
    try:
        if hasattr(view, "PointColor"):
            view.PointColor = (0.18, 0.55, 0.95)
    except Exception:
        pass
    try:
        if hasattr(view, "LineWidth"):
            view.LineWidth = 2.0
    except Exception:
        pass
    try:
        if hasattr(view, "Transparency"):
            view.Transparency = 0
    except Exception:
        pass


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
    _log("create_involute_gear_start", document=getattr(document, "Name", ""), op=op)
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
    base_face = Part.Face(gear_wire)

    created = []
    _log("create_involute_gear_profile_step_start", name=name + "Profile")
    profile = document.addObject("Part::Feature", name + "Profile")
    profile.Shape = base_face
    created.append(profile.Name)
    document.recompute()
    _log(
        "create_involute_gear_profile_created",
        object_name=profile.Name,
        shape_type=str(getattr(getattr(profile, "Shape", None), "ShapeType", "")),
    )

    result = profile
    if thickness > 0.0:
        # Use Part::Extrusion to compute the shape (returns proper Part.Shape
        # via C++ property getter), then IMMEDIATELY copy shape and remove the
        # Part::Extrusion object. Part::Extrusion has a Base PropertyLink that
        # causes SIGSEGV when FreeCAD's internal timer calls
        # ViewProviderExtrusion::claimChildren() → PropertyLink::getValue().
        # By removing it before returning, we prevent the crash.
        _log("create_involute_gear_extrusion_step_start", base=profile.Name, thickness=thickness)
        tmp_extrusion = document.addObject("Part::Extrusion", name + "TmpExtrusion")
        tmp_extrusion.Base = profile
        tmp_extrusion.LengthFwd = thickness
        tmp_extrusion.Solid = True
        document.recompute()
        extruded_shape = tmp_extrusion.Shape.copy()
        # Remove the Part::Extrusion immediately to prevent PropertyLink crash
        document.removeObject(tmp_extrusion.Name)
        document.recompute()
        # Store the computed shape in a safe Part::Feature (no PropertyLinks)
        extrusion = document.addObject("Part::Feature", name + "Extrusion")
        extrusion.Shape = extruded_shape
        created.append(extrusion.Name)
        document.recompute()
        result = extrusion
        _log(
            "create_involute_gear_extrusion_created",
            object_name=extrusion.Name,
            shape_type=str(getattr(getattr(extrusion, "Shape", None), "ShapeType", "")),
            volume=float(getattr(getattr(extrusion, "Shape", None), "Volume", 0.0)),
        )
        try:
            profile.ViewObject.Visibility = False
        except Exception:
            pass

    if thickness > 0.0 and bore > 0.0:
        _log("create_involute_gear_bore_step_start", base=result.Name, bore=bore, thickness=thickness)
        # Use Part::Cylinder to get proper Part.Shape, then remove it
        tmp_bore = document.addObject("Part::Cylinder", name + "TmpBore")
        tmp_bore.Radius = bore / 2.0
        tmp_bore.Height = thickness
        document.recompute()
        bore_tool_shape = tmp_bore.Shape.copy()
        document.removeObject(tmp_bore.Name)

        final_shape = result.Shape.cut(bore_tool_shape)
        cut = document.addObject("Part::Feature", name)
        cut.Shape = final_shape
        created.append(cut.Name)
        result = cut
        _log(
            "create_involute_gear_cut_created",
            object_name=cut.Name,
            shape_type=str(getattr(final_shape, "ShapeType", "")),
            volume=float(getattr(final_shape, "Volume", 0.0)),
        )
        try:
            extrusion.ViewObject.Visibility = False
        except Exception:
            pass
        try:
            profile.ViewObject.Visibility = False
        except Exception:
            pass
    elif thickness <= 0.0:
        _style_created_object(profile)

    document.recompute()
    _style_created_object(result)
    return _success(created=created, result_object=result.Name)


def _create_body(document, op):
    name = op.get("name", "Body")
    # FreeCAD's PartDesign::Body creation is not reliable in this sidecar path on
    # the current build. Create a visible primitive instead so tool calls produce
    # immediate on-canvas geometry.
    return _create_box(document, {"name": name})


def _create_box(document, op):
    name = op.get("name", "Box")
    length = float(op.get("length", op.get("x", 10.0)) or 10.0)
    width = float(op.get("width", op.get("y", 10.0)) or 10.0)
    height = float(op.get("height", op.get("z", 10.0)) or 10.0)
    box = document.addObject("Part::Box", name)
    box.Length = length
    box.Width = width
    box.Height = height
    _style_created_object(box)
    _log(
        "create_box_created",
        object_name=getattr(box, "Name", ""),
        length=length,
        width=width,
        height=height,
    )
    return _success(created=[box.Name], result_object=box.Name)


def _create_cylinder(document, op):
    name = op.get("name", "Cylinder")
    radius = float(op.get("radius", 5.0) or 5.0)
    height = float(op.get("height", op.get("z", 10.0)) or 10.0)
    cylinder = document.addObject("Part::Cylinder", name)
    cylinder.Radius = radius
    cylinder.Height = height
    _style_created_object(cylinder)
    _log(
        "create_cylinder_created",
        object_name=getattr(cylinder, "Name", ""),
        radius=radius,
        height=height,
    )
    return _success(created=[cylinder.Name], result_object=cylinder.Name)


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
    if op_name == "create_cylinder":
        return _create_cylinder(document, op)
    if op_name == "create_body":
        return _create_body(document, op)
    if op_name == "create_box":
        return _create_box(document, op)
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

    _log("apply_ops_start", document=getattr(document, "Name", ""), transaction_name=transaction_name, ops=ops)
    results = []
    
    # We intentionally bypass explicit document.openTransaction() because
    # FreeCAD can sometimes be left in a mid-transaction state ("Cannot
    # commit transaction while transacting"), which aborts our entire script
    # and erases the created features. We'll simply let the document auto-handle
    # undo groups or rely on our caller.
    try:
        for op in ops:
            result = _apply_operation(document, op)
            results.append({"op": op, "result": result})
            if not result.get("ok", False):
                raise RuntimeError(result.get("error", "Operation failed"))
        document.recompute()
        _log("apply_ops_success", document=getattr(document, "Name", ""), results=results)
        return _success(results=results)
    except Exception as exc:
        _log("apply_ops_failure", document=getattr(document, "Name", ""), error=str(exc), results=results, traceback=traceback.format_exc())
        return _failure(str(exc), results=results, traceback=traceback.format_exc())


def execute_tool_request(tool_request, document=None):
    tool_name = tool_request.get("tool_name", "")
    arguments = tool_request.get("arguments", {})
    _log("execute_tool_request", tool_name=tool_name, arguments=arguments, document=getattr(_document(document), "Name", ""))
    if tool_name == "get_object_details":
        return get_object_details(document=document, object_name=arguments.get("object_name", ""))
    if tool_name == "get_document_snapshot":
        import Snapshot

        return _success(snapshot=Snapshot.build_document_snapshot(document=document, selection_only=arguments.get("selection_only", False)))
    if tool_name == "apply_ops":
        return apply_ops(arguments.get("ops", []), document=document)
    return _failure("Unsupported tool request '{0}'".format(tool_name))
