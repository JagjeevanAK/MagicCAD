# SPDX-License-Identifier: LGPL-2.1-or-later

import hashlib
import json

import FreeCAD

from SessionObjects import REPORT_NAME, ROOT_NAME, SESSION_NAME

try:
    import FreeCADGui
except ImportError:
    FreeCADGui = None


def _coerce_value(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce_value(item) for item in value]
    if hasattr(value, "Value"):
        return value.Value
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return [value.x, value.y, value.z]
    return str(value)


def _selection_refs(document):
    refs = []
    if not FreeCAD.GuiUp or FreeCADGui is None:
        return refs
    for selection in FreeCADGui.Selection.getSelectionEx(document.Name):
        ref = {
            "object_name": selection.ObjectName,
            "subelements": list(selection.SubElementNames or []),
        }
        refs.append(ref)
    return refs


def _selected_object_names(document):
    return {ref["object_name"] for ref in _selection_refs(document)}


def _expand_selection(document, names):
    expanded = set(names)
    for name in list(names):
        obj = document.getObject(name)
        if obj is None:
            continue
        for linked in getattr(obj, "InList", []):
            expanded.add(linked.Name)
        for linked in getattr(obj, "OutList", []):
            expanded.add(linked.Name)
    return [document.getObject(name) for name in sorted(expanded) if document.getObject(name)]


def _shape_metrics(obj):
    if not hasattr(obj, "Shape"):
        return {}

    try:
        shape = obj.Shape
    except Exception:
        return {}

    metrics = {
        "has_shape": True,
        "is_null": False,
        "shape_type": str(getattr(shape, "ShapeType", "")),
        "vertex_count": 0,
        "edge_count": 0,
        "face_count": 0,
        "solid_count": 0,
        "area": 0.0,
        "volume": 0.0,
        "tiny_edge_count": 0,
        "tiny_face_count": 0,
        "bbox": {},
    }
    try:
        metrics["is_null"] = bool(shape.isNull())
    except Exception:
        metrics["is_null"] = False
    try:
        metrics["vertex_count"] = len(shape.Vertexes)
        metrics["edge_count"] = len(shape.Edges)
        metrics["face_count"] = len(shape.Faces)
        metrics["solid_count"] = len(shape.Solids)
    except Exception:
        pass
    try:
        metrics["area"] = float(getattr(shape, "Area", 0.0))
    except Exception:
        pass
    try:
        metrics["volume"] = float(getattr(shape, "Volume", 0.0))
    except Exception:
        pass
    try:
        bbox = shape.BoundBox
        metrics["bbox"] = {
            "x": float(bbox.XLength),
            "y": float(bbox.YLength),
            "z": float(bbox.ZLength),
        }
    except Exception:
        metrics["bbox"] = {}
    try:
        metrics["tiny_edge_count"] = sum(1 for edge in shape.Edges if getattr(edge, "Length", 1.0) < 0.1)
    except Exception:
        pass
    try:
        metrics["tiny_face_count"] = sum(1 for face in shape.Faces if getattr(face, "Area", 1.0) < 0.01)
    except Exception:
        pass
    return metrics


def _sketch_metrics(obj):
    if not obj.TypeId.startswith("Sketcher::") and not hasattr(obj, "Geometry"):
        return {}

    metrics = {}
    for name in (
        "GeometryCount",
        "ConstraintCount",
        "ExternalGeometryCount",
        "FullyConstrained",
        "DegreeOfFreedom",
    ):
        if hasattr(obj, name):
            metrics[name.lower()] = _coerce_value(getattr(obj, name))
    try:
        metrics["geometry_count"] = len(obj.Geometry)
    except Exception:
        pass
    try:
        metrics["constraint_count"] = len(obj.Constraints)
    except Exception:
        pass
    try:
        metrics["external_geometry_count"] = len(obj.ExternalGeometry)
    except Exception:
        pass
    return metrics


def summarize_object(obj):
    summary = {
        "name": obj.Name,
        "label": obj.Label,
        "type_id": obj.TypeId,
        "state": list(getattr(obj, "State", [])),
        "in_list": [linked.Name for linked in getattr(obj, "InList", [])],
        "out_list": [linked.Name for linked in getattr(obj, "OutList", [])],
        "parameters": {},
        "placement": {},
        "shape": _shape_metrics(obj),
        "sketch": _sketch_metrics(obj),
    }
    try:
        placement = obj.Placement
        summary["placement"] = {
            "base": [placement.Base.x, placement.Base.y, placement.Base.z],
        }
    except Exception:
        summary["placement"] = {}

    for prop_name in getattr(obj, "PropertiesList", []):
        try:
            type_name = obj.getTypeIdOfProperty(prop_name)
        except Exception:
            type_name = ""
        if not type_name.startswith("App::Property"):
            continue
        if not any(token in type_name for token in ("Length", "Angle", "Float", "Integer", "Bool", "String", "Quantity")):
            continue
        try:
            summary["parameters"][prop_name] = {
                "type": type_name,
                "value": _coerce_value(getattr(obj, prop_name)),
            }
        except Exception:
            continue
    return summary


def _collect_parameters(objects):
    params = []
    for obj in objects:
        for name, entry in summarize_object(obj)["parameters"].items():
            params.append(
                {
                    "object_name": obj.Name,
                    "object_label": obj.Label,
                    "name": name,
                    "type": entry.get("type", ""),
                    "value": entry.get("value"),
                }
            )
    return params


def _collect_dependency_edges(objects):
    names = {obj.Name for obj in objects}
    edges = []
    for obj in objects:
        for linked in getattr(obj, "OutList", []):
            if linked.Name in names:
                edges.append({"from": obj.Name, "to": linked.Name})
    return edges


def _collect_recompute_errors(objects):
    errors = []
    for obj in objects:
        states = list(getattr(obj, "State", []))
        bad = [state for state in states if "error" in state.lower() or "invalid" in state.lower()]
        if bad:
            errors.append({"object_name": obj.Name, "states": bad})
    return errors


def build_document_snapshot(document=None, selection_only=False):
    document = document or FreeCAD.ActiveDocument
    if document is None:
        return None

    selected_names = _selected_object_names(document)
    internal_names = {ROOT_NAME, SESSION_NAME, REPORT_NAME}
    objects = [obj for obj in document.Objects if obj.Name not in internal_names]
    if selection_only and selected_names:
        objects = _expand_selection(document, selected_names)

    object_summaries = [summarize_object(obj) for obj in objects]
    active_object = getattr(document, "ActiveObject", None)
    snapshot = {
        "document_id": getattr(document, "Uid", document.Name),
        "document_name": document.Name,
        "document_label": document.Label,
        "units": FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("UserSchema", 0),
        "active_workbench": "",
        "active_object_id": active_object.Name if active_object else "",
        "selection": _selection_refs(document),
        "parameters": _collect_parameters(objects),
        "objects": object_summaries,
        "dependency_edges": _collect_dependency_edges(objects),
        "recompute_errors": _collect_recompute_errors(objects),
    }
    if FreeCAD.GuiUp and FreeCADGui is not None:
        try:
            snapshot["active_workbench"] = FreeCADGui.activeWorkbench().name()
        except Exception:
            snapshot["active_workbench"] = ""

    digest_source = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot["snapshot_hash"] = hashlib.sha256(digest_source).hexdigest()
    return snapshot
