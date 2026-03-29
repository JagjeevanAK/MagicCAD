# SPDX-License-Identifier: LGPL-2.1-or-later

import collections
import uuid


SEVERITY_WEIGHT = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _issue(rule_id, severity, category, message, recommendation, object_ref=None, evidence=None, confidence=0.75):
    return {
        "issue_id": uuid.uuid4().hex,
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "source": "deterministic",
        "confidence": confidence,
        "object_ref": object_ref or {},
        "subelement_ref": {},
        "evidence": evidence or {},
        "message": message,
        "recommended_fix": recommendation,
        "highlight_mode": "object",
    }


def _find_duplicate_labels(snapshot):
    issues = []
    labels = collections.defaultdict(list)
    for obj in snapshot.get("objects", []):
        labels[obj.get("label", "").strip()].append(obj)
    for label, objects in labels.items():
        if not label or len(objects) < 2:
            continue
        names = [obj["name"] for obj in objects]
        issues.append(
            _issue(
                "duplicate-labels",
                "medium",
                "naming",
                "Duplicate label '{0}' found on {1} objects.".format(label, len(objects)),
                "Rename the colliding objects so downstream reports and selections stay unambiguous.",
                object_ref={"object_name": names[0], "object_names": names},
                evidence={"labels": names},
                confidence=0.95,
            )
        )
    return issues


def _find_recompute_errors(snapshot):
    issues = []
    for entry in snapshot.get("recompute_errors", []):
        issues.append(
            _issue(
                "recompute-error",
                "high",
                "recompute",
                "Object '{0}' is flagged with recompute/error states: {1}.".format(
                    entry.get("object_name", ""), ", ".join(entry.get("states", []))
                ),
                "Recompute the model and inspect the failing feature or its dependencies.",
                object_ref={"object_name": entry.get("object_name", "")},
                evidence=entry,
                confidence=0.98,
            )
        )
    return issues


def _find_null_or_invalid_shapes(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        shape = obj.get("shape", {})
        if not shape:
            continue
        if shape.get("is_null"):
            issues.append(
                _issue(
                    "null-shape",
                    "high",
                    "geometry",
                    "Object '{0}' currently has a null shape.".format(obj.get("label", obj.get("name", ""))),
                    "Inspect the generating feature and recompute after fixing the missing geometry input.",
                    object_ref={"object_name": obj.get("name", "")},
                    evidence={"shape": shape},
                    confidence=0.92,
                )
            )
        if obj.get("type_id", "").startswith("PartDesign::") and shape.get("face_count", 0) > 0 and shape.get("solid_count", 0) == 0:
            issues.append(
                _issue(
                    "non-solid-partdesign",
                    "high",
                    "geometry",
                    "PartDesign object '{0}' is producing faces but no solid.".format(obj.get("label", obj.get("name", ""))),
                    "Check support references, sketch closure, and feature parameters to restore a valid solid.",
                    object_ref={"object_name": obj.get("name", "")},
                    evidence={"shape": shape},
                    confidence=0.85,
                )
            )
    return issues


def _find_tiny_geometry(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        shape = obj.get("shape", {})
        if not shape:
            continue
        tiny_edges = int(shape.get("tiny_edge_count", 0))
        tiny_faces = int(shape.get("tiny_face_count", 0))
        if tiny_edges > 0 or tiny_faces > 0:
            issues.append(
                _issue(
                    "tiny-geometry",
                    "medium",
                    "manufacturability",
                    "Object '{0}' contains {1} tiny edges and {2} tiny faces.".format(
                        obj.get("label", obj.get("name", "")), tiny_edges, tiny_faces
                    ),
                    "Review fillets, offsets, and imported detail that may be smaller than the intended model tolerance.",
                    object_ref={"object_name": obj.get("name", "")},
                    evidence={"shape": shape},
                    confidence=0.8,
                )
            )
    return issues


def _find_sketch_risks(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        sketch = obj.get("sketch", {})
        if not sketch:
            continue
        geometry_count = int(sketch.get("geometry_count", 0) or 0)
        constraint_count = int(sketch.get("constraint_count", 0) or 0)
        dof = sketch.get("degreeoffreedom", sketch.get("degree_of_freedom"))
        if geometry_count == 0:
            issues.append(
                _issue(
                    "empty-sketch",
                    "medium",
                    "sketch",
                    "Sketch '{0}' has no geometry.".format(obj.get("label", obj.get("name", ""))),
                    "Delete the empty sketch or add the intended profile before downstream features depend on it.",
                    object_ref={"object_name": obj.get("name", "")},
                    evidence={"sketch": sketch},
                    confidence=0.99,
                )
            )
            continue
        if constraint_count == 0:
            issues.append(
                _issue(
                    "unconstrained-sketch",
                    "medium",
                    "sketch",
                    "Sketch '{0}' has geometry but no constraints.".format(obj.get("label", obj.get("name", ""))),
                    "Add dimensional and geometric constraints so the profile stays stable under edits.",
                    object_ref={"object_name": obj.get("name", "")},
                    evidence={"sketch": sketch},
                    confidence=0.84,
                )
            )
        elif dof not in (None, "", 0, False):
            issues.append(
                _issue(
                    "underconstrained-sketch",
                    "low",
                    "sketch",
                    "Sketch '{0}' reports remaining degrees of freedom: {1}.".format(
                        obj.get("label", obj.get("name", "")), dof
                    ),
                    "Finish constraining the sketch or document why remaining freedom is intentional.",
                    object_ref={"object_name": obj.get("name", "")},
                    evidence={"sketch": sketch},
                    confidence=0.78,
                )
            )
    return issues


def _find_naming_inconsistencies(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        label = obj.get("label", "")
        if label.endswith(tuple(str(i).zfill(3) for i in range(1, 10))) and label == obj.get("name", ""):
            issues.append(
                _issue(
                    "autogenerated-name",
                    "low",
                    "naming",
                    "Object '{0}' still uses an autogenerated name.".format(label),
                    "Rename critical model features so review and validation reports stay readable.",
                    object_ref={"object_name": obj.get("name", "")},
                    evidence={"label": label},
                    confidence=0.65,
                )
            )
    return issues


def validate_snapshot(snapshot):
    if not snapshot:
        return []

    issues = []
    issues.extend(_find_recompute_errors(snapshot))
    issues.extend(_find_duplicate_labels(snapshot))
    issues.extend(_find_null_or_invalid_shapes(snapshot))
    issues.extend(_find_tiny_geometry(snapshot))
    issues.extend(_find_sketch_risks(snapshot))
    issues.extend(_find_naming_inconsistencies(snapshot))
    issues.sort(key=lambda entry: SEVERITY_WEIGHT.get(entry.get("severity", "low"), 0), reverse=True)
    return issues


def issue_counts(issues):
    counts = collections.Counter(issue.get("severity", "low") for issue in issues)
    counts["total"] = len(issues)
    return dict(counts)
