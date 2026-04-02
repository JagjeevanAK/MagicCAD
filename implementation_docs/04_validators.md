# Validators Module

## Purpose

The Validators module runs deterministic, rule-based checks on the FreeCAD model **before** calling the AI. This provides fast, explainable validation without LLM costs.

---

## File Location

```
src/Mod/MagicCADAI/Validators.py
```

---

## Design Philosophy

1. **Rule-First**: Run deterministic validators before AI
2. **Explainable**: Each rule has clear logic and evidence
3. **Severity-Weighted**: Issues sorted by severity
4. **Confidence-Scored**: Each issue has confidence level

---

## Main Function

```python
def validate_snapshot(snapshot):
    """
    Run all deterministic validators on snapshot.
    
    Args:
        snapshot: DocumentSnapshot from Snapshot.py
    
    Returns:
        List[ValidationIssue] sorted by severity (descending)
    """
    if not snapshot:
        return []
    
    issues = []
    issues.extend(_find_recompute_errors(snapshot))
    issues.extend(_find_duplicate_labels(snapshot))
    issues.extend(_find_null_or_invalid_shapes(snapshot))
    issues.extend(_find_tiny_geometry(snapshot))
    issues.extend(_find_sketch_risks(snapshot))
    issues.extend(_find_naming_inconsistencies(snapshot))
    
    # Sort by severity
    issues.sort(key=lambda e: SEVERITY_WEIGHT.get(e["severity"], 0), 
                reverse=True)
    
    return issues
```

---

## Severity Levels

```python
SEVERITY_WEIGHT = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}
```

---

## Validator Rules

### 1. Recompute Errors

**Function:** `_find_recompute_errors(snapshot)`

**Checks:** Objects flagged with error/invalid states

**Severity:** High

**Confidence:** 0.98

```python
def _find_recompute_errors(snapshot):
    issues = []
    for entry in snapshot.get("recompute_errors", []):
        issues.append(_issue(
            "recompute-error",
            "high",
            "recompute",
            "Object '{0}' is flagged with recompute/error states: {1}.".format(
                entry.get("object_name", ""), 
                ", ".join(entry.get("states", []))
            ),
            "Recompute the model and inspect the failing feature or its dependencies.",
            object_ref={"object_name": entry.get("object_name", "")},
            evidence=entry,
            confidence=0.98,
        ))
    return issues
```

**Example Issue:**
```json
{
  "rule_id": "recompute-error",
  "severity": "high",
  "category": "recompute",
  "message": "Object 'Pad001' is flagged with recompute/error states: ['Error']",
  "recommended_fix": "Recompute the model and inspect the failing feature",
  "object_ref": {"object_name": "Pad001"},
  "evidence": {"object_name": "Pad001", "states": ["Error"]},
  "confidence": 0.98
}
```

---

### 2. Duplicate Labels

**Function:** `_find_duplicate_labels(snapshot)`

**Checks:** Multiple objects with same label

**Severity:** Medium

**Confidence:** 0.95

```python
def _find_duplicate_labels(snapshot):
    issues = []
    labels = collections.defaultdict(list)
    
    for obj in snapshot.get("objects", []):
        labels[obj.get("label", "").strip()].append(obj)
    
    for label, objects in labels.items():
        if not label or len(objects) < 2:
            continue
        
        names = [obj["name"] for obj in objects]
        issues.append(_issue(
            "duplicate-labels",
            "medium",
            "naming",
            "Duplicate label '{0}' found on {1} objects.".format(
                label, len(objects)
            ),
            "Rename the colliding objects so downstream reports and selections stay unambiguous.",
            object_ref={"object_name": names[0], "object_names": names},
            evidence={"labels": names},
            confidence=0.95,
        ))
    return issues
```

**Why It Matters:**
- Ambiguous selection in scripts
- Confusing reports
- Hard to debug

---

### 3. Null or Invalid Shapes

**Function:** `_find_null_or_invalid_shapes(snapshot)`

**Checks:**
- Objects with null shapes (failed operations)
- PartDesign objects producing faces instead of solids

**Severity:** High

**Confidence:** 0.92 (null), 0.85 (non-solid)

```python
def _find_null_or_invalid_shapes(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        shape = obj.get("shape", {})
        if not shape:
            continue
        
        # Check for null shape
        if shape.get("is_null"):
            issues.append(_issue(
                "null-shape",
                "high",
                "geometry",
                "Object '{0}' currently has a null shape.".format(
                    obj.get("label", obj.get("name", ""))
                ),
                "Inspect the generating feature and recompute after fixing the missing geometry input.",
                object_ref={"object_name": obj.get("name", "")},
                evidence={"shape": shape},
                confidence=0.92,
            ))
        
        # Check for non-solid PartDesign (faces but no solid)
        if (obj.get("type_id", "").startswith("PartDesign::") and 
            shape.get("face_count", 0) > 0 and 
            shape.get("solid_count", 0) == 0):
            issues.append(_issue(
                "non-solid-partdesign",
                "high",
                "geometry",
                "PartDesign object '{0}' is producing faces but no solid.".format(
                    obj.get("label", obj.get("name", ""))
                ),
                "Check support references, sketch closure, and feature parameters to restore a valid solid.",
                object_ref={"object_name": obj.get("name", "")},
                evidence={"shape": shape},
                confidence=0.85,
            ))
    return issues
```

**Why Non-Solid is Bad:**
- PartDesign expects solid bodies
- Boolean operations fail
- Downstream features break

---

### 4. Tiny Geometry

**Function:** `_find_tiny_geometry(snapshot)`

**Checks:** Edges < 0.1mm, faces < 0.01mm²

**Severity:** Medium

**Confidence:** 0.80

```python
def _find_tiny_geometry(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        shape = obj.get("shape", {})
        if not shape:
            continue
        
        tiny_edges = int(shape.get("tiny_edge_count", 0))
        tiny_faces = int(shape.get("tiny_face_count", 0))
        
        if tiny_edges > 0 or tiny_faces > 0:
            issues.append(_issue(
                "tiny-geometry",
                "medium",
                "manufacturability",
                "Object '{0}' contains {1} tiny edges and {2} tiny faces.".format(
                    obj.get("label", obj.get("name", "")), 
                    tiny_edges, tiny_faces
                ),
                "Review fillets, offsets, and imported detail that may be smaller than the intended model tolerance.",
                object_ref={"object_name": obj.get("name", "")},
                evidence={"shape": shape},
                confidence=0.8,
            ))
    return issues
```

**Why It Matters:**
- Manufacturing tolerance issues
- 3D printing artifacts
- Mesh generation failures
- Import/export problems

---

### 5. Sketch Risks

**Function:** `_find_sketch_risks(snapshot)`

**Checks:**
- Empty sketches (no geometry)
- Unconstrained sketches (no constraints)
- Underconstrained sketches (DOF > 0)

**Severity:** Medium (empty, unconstrained), Low (underconstrained)

**Confidence:** 0.99 (empty), 0.84 (unconstrained), 0.78 (underconstrained)

```python
def _find_sketch_risks(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        sketch = obj.get("sketch", {})
        if not sketch:
            continue
        
        geometry_count = int(sketch.get("geometry_count", 0) or 0)
        constraint_count = int(sketch.get("constraint_count", 0) or 0)
        dof = sketch.get("degreeoffreedom", sketch.get("degree_of_freedom"))
        
        # Empty sketch
        if geometry_count == 0:
            issues.append(_issue(
                "empty-sketch",
                "medium",
                "sketch",
                "Sketch '{0}' has no geometry.".format(
                    obj.get("label", obj.get("name", ""))
                ),
                "Delete the empty sketch or add the intended profile before downstream features depend on it.",
                object_ref={"object_name": obj.get("name", "")},
                evidence={"sketch": sketch},
                confidence=0.99,
            ))
            continue
        
        # No constraints
        if constraint_count == 0:
            issues.append(_issue(
                "unconstrained-sketch",
                "medium",
                "sketch",
                "Sketch '{0}' has geometry but no constraints.".format(
                    obj.get("label", obj.get("name", ""))
                ),
                "Add dimensional and geometric constraints so the profile stays stable under edits.",
                object_ref={"object_name": obj.get("name", "")},
                evidence={"sketch": sketch},
                confidence=0.84,
            ))
        # Underconstrained (DOF > 0)
        elif dof not in (None, "", 0, False):
            issues.append(_issue(
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
            ))
    return issues
```

**Why Constraints Matter:**
- Unconstrained sketches change unexpectedly
- Parametric edits break
- Design intent not captured

---

### 6. Naming Inconsistencies

**Function:** `_find_naming_inconsistencies(snapshot)`

**Checks:** Objects using auto-generated names

**Severity:** Low

**Confidence:** 0.65

```python
def _find_naming_inconsistencies(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        label = obj.get("label", "")
        
        # Check if using default name pattern (e.g., "Pad001")
        if (label.endswith(tuple(str(i).zfill(3) for i in range(1, 10))) and 
            label == obj.get("name", "")):
            issues.append(_issue(
                "autogenerated-name",
                "low",
                "naming",
                "Object '{0}' still uses an autogenerated name.".format(label),
                "Rename critical model features so review and validation reports stay readable.",
                object_ref={"object_name": obj.get("name", "")},
                evidence={"label": label},
                confidence=0.65,
            ))
    return issues
```

**Why It Matters:**
- Hard to read reports
- Confusing feature tree
- Script references break on model changes

---

## Issue Helper Function

```python
def _issue(rule_id, severity, category, message, recommendation, 
           object_ref=None, evidence=None, confidence=0.75):
    """Create a ValidationIssue dict."""
    return {
        "issue_id": uuid.uuid4().hex,
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "source": "deterministic",  # vs "llm"
        "confidence": confidence,
        "object_ref": object_ref or {},
        "subelement_ref": {},
        "evidence": evidence or {},
        "message": message,
        "recommended_fix": recommendation,
        "highlight_mode": "object",
    }
```

---

## Issue Counts Helper

```python
def issue_counts(issues):
    """Count issues by severity."""
    counts = collections.Counter(
        issue.get("severity", "low") for issue in issues
    )
    counts["total"] = len(issues)
    return dict(counts)
```

**Output:**
```json
{
  "high": 2,
  "medium": 3,
  "low": 1,
  "total": 6
}
```

---

## ValidationIssue Structure

```json
{
  "issue_id": "uuid-here",
  "rule_id": "null-shape",
  "severity": "high",
  "category": "geometry",
  "source": "deterministic",
  "confidence": 0.92,
  "object_ref": {
    "object_name": "Body001"
  },
  "subelement_ref": {},
  "evidence": {
    "shape": {"is_null": true, ...}
  },
  "message": "Object has null shape",
  "recommended_fix": "Inspect the generating feature",
  "highlight_mode": "object"
}
```

---

## Extension Points

To add a new validator:

1. Create a new `_find_*` function:
```python
def _find_custom_check(snapshot):
    issues = []
    for obj in snapshot.get("objects", []):
        if _check_condition(obj):
            issues.append(_issue(
                "custom-rule",
                "medium",
                "custom",
                "Custom message",
                "Custom recommendation",
                object_ref={"object_name": obj.get("name", "")},
                evidence={"custom": "data"},
                confidence=0.85,
            ))
    return issues
```

2. Add to `validate_snapshot()`:
```python
def validate_snapshot(snapshot):
    issues = []
    # ... existing validators
    issues.extend(_find_custom_check(snapshot))
    issues.sort(...)
    return issues
```

---

## Performance

| Validator | Complexity | Notes |
|-----------|------------|-------|
| `recompute_errors` | O(n) | Already collected in snapshot |
| `duplicate_labels` | O(n) | Simple dict grouping |
| `null_or_invalid_shapes` | O(n) | Shape data pre-extracted |
| `tiny_geometry` | O(n) | Metrics pre-computed |
| `sketch_risks` | O(n) | Sketch data pre-extracted |
| `naming_inconsistencies` | O(n) | String comparison |

**Total:** O(n) where n = number of objects

---

## Related Documents

- `03_snapshot_extraction.md` - Snapshot data structure
- `02_data_flow.md` - When validators run in flow
- `05_ai_integration.md` - How AI uses validator results
