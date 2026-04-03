# Snapshot Extraction

## Purpose

The Snapshot module extracts the FreeCAD document's internal data model as structured JSON. This JSON is sent to the AI for analysis.

**Key Design Decision:** Uses structured data extraction, NOT screenshots or images.

---

## File Location

```
src/Mod/MagicCADAI/Snapshot.py
```

---

## Main Function

```python
def build_document_snapshot(document=None, selection_only=False):
    """
    Extract complete document state as JSON-serializable dict.
    
    Args:
        document: FreeCAD document (default: ActiveDocument)
        selection_only: If True, only extract selected objects + dependencies
    
    Returns:
        Dict with document metadata, objects, parameters, edges, errors
    """
```

---

## Extraction Process

### Step 1: Get Selection

```python
def _selection_refs(document):
    refs = []
    if not FreeCAD.GuiUp:
        return refs
    
    for selection in FreeCADGui.Selection.getSelectionEx(document.Name):
        ref = {
            "object_name": selection.ObjectName,
            "subelements": list(selection.SubElementNames or []),
        }
        refs.append(ref)
    return refs
```

**Extracts:**
- Selected object names
- Sub-element references (Edge1, Face2, etc.)

---

### Step 2: Filter Objects

```python
# Exclude internal MagicCAD objects
internal_names = {ROOT_NAME, SESSION_NAME, REPORT_NAME}
# = {"MagicCADAIData", "MagicCADAISession", "MagicCADAIReport"}

objects = [obj for obj in document.Objects 
           if obj.Name not in internal_names]

# If selection_only, expand to include dependencies
if selection_only and selected_names:
    objects = _expand_selection(document, selected_names)
```

**Expansion Logic:**
```python
def _expand_selection(document, names):
    expanded = set(names)
    for name in list(names):
        obj = document.getObject(name)
        # Add objects this one depends on (InList)
        for linked in getattr(obj, "InList", []):
            expanded.add(linked.Name)
        # Add objects that depend on this one (OutList)
        for linked in getattr(obj, "OutList", []):
            expanded.add(linked.Name)
    return [document.getObject(name) for name in sorted(expanded)]
```

---

### Step 3: Summarize Each Object

```python
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
    
    # Extract relevant properties
    for prop_name in getattr(obj, "PropertiesList", []):
        type_name = obj.getTypeIdOfProperty(prop_name)
        if not _is_relevant_property(type_name):
            continue
        summary["parameters"][prop_name] = {
            "type": type_name,
            "value": _coerce_value(getattr(obj, prop_name)),
        }
    
    return summary
```

---

### Step 4: Extract Shape Metrics

```python
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
    
    # Populate metrics
    try:
        metrics["is_null"] = bool(shape.isNull())
    except Exception:
        pass
    
    try:
        metrics["vertex_count"] = len(shape.Vertexes)
        metrics["edge_count"] = len(shape.Edges)
        metrics["face_count"] = len(shape.Faces)
        metrics["solid_count"] = len(shape.Solids)
    except Exception:
        pass
    
    try:
        metrics["area"] = float(getattr(shape, "Area", 0.0))
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
        pass
    
    # Detect tiny geometry (manufacturing risk)
    try:
        metrics["tiny_edge_count"] = sum(
            1 for edge in shape.Edges 
            if getattr(edge, "Length", 1.0) < 0.1
        )
        metrics["tiny_face_count"] = sum(
            1 for face in shape.Faces 
            if getattr(face, "Area", 1.0) < 0.01
        )
    except Exception:
        pass
    
    return metrics
```

**Metrics Extracted:**

| Metric | Purpose |
|--------|---------|
| `is_null` | Detect failed geometry operations |
| `shape_type` | Vertex, Edge, Wire, Face, Shell, Solid, Compound |
| `vertex_count` | Complexity measure |
| `edge_count` | Complexity measure |
| `face_count` | Complexity measure |
| `solid_count` | Verify solid body (PartDesign requirement) |
| `area` | Surface area |
| `volume` | Mass/volume calculations |
| `tiny_edge_count` | Manufacturing risk (< 0.1mm) |
| `tiny_face_count` | Manufacturing risk (< 0.01mm²) |
| `bbox` | Bounding box dimensions |

---

### Step 5: Extract Sketch Metrics

```python
def _sketch_metrics(obj):
    # Check if it's a sketch
    if not obj.TypeId.startswith("Sketcher::") and not hasattr(obj, "Geometry"):
        return {}
    
    metrics = {}
    
    # Built-in properties
    for name in ("GeometryCount", "ConstraintCount", 
                 "ExternalGeometryCount", "FullyConstrained", 
                 "DegreeOfFreedom"):
        if hasattr(obj, name):
            metrics[name.lower()] = _coerce_value(getattr(obj, name))
    
    # Direct geometry access
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
```

**Metrics Extracted:**

| Metric | Purpose |
|--------|---------|
| `geometry_count` | Number of curves (lines, arcs, etc.) |
| `constraint_count` | Number of constraints |
| `external_geometry_count` | References to external geometry |
| `fully_constrained` | Boolean: sketch fully defined |
| `degree_of_freedom` | Remaining DOF (0 = fully constrained) |

---

### Step 6: Extract Parameters

```python
def _collect_parameters(objects):
    params = []
    for obj in objects:
        for name, entry in summarize_object(obj)["parameters"].items():
            params.append({
                "object_name": obj.Name,
                "object_label": obj.Label,
                "name": name,
                "type": entry.get("type", ""),
                "value": entry.get("value"),
            })
    return params
```

**Property Types Extracted:**
- `App::PropertyLength` - Length dimensions
- `App::PropertyAngle` - Angle dimensions
- `App::PropertyFloat` - Floating point values
- `App::PropertyInteger` - Integer values
- `App::PropertyBool` - Boolean flags
- `App::PropertyString` - Text values
- `App::PropertyQuantity` - Physical quantities

---

### Step 7: Extract Dependency Graph

```python
def _collect_dependency_edges(objects):
    names = {obj.Name for obj in objects}
    edges = []
    for obj in objects:
        for linked in getattr(obj, "OutList", []):
            if linked.Name in names:
                edges.append({"from": obj.Name, "to": linked.Name})
    return edges
```

**Purpose:** Understand feature tree structure for:
- Impact analysis (what breaks if I change this?)
- Root cause analysis (what caused this error?)
- Ordered validation (check parents first)

---

### Step 8: Extract Recompute Errors

```python
def _collect_recompute_errors(objects):
    errors = []
    for obj in objects:
        states = list(getattr(obj, "State", []))
        bad = [state for state in states 
               if "error" in state.lower() or "invalid" in state.lower()]
        if bad:
            errors.append({
                "object_name": obj.Name, 
                "states": bad
            })
    return errors
```

**Purpose:** Detect failed features that need attention.

---

### Step 9: Compute Snapshot Hash

```python
digest_source = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
snapshot["snapshot_hash"] = hashlib.sha256(digest_source).hexdigest()
```

**Purpose:**
- Detect if model changed since last validation
- Cache validation results
- Avoid redundant AI calls

---

## Complete Snapshot Structure

```json
{
  "document_id": "uuid-here",
  "document_name": "Document",
  "document_label": "My Assembly",
  "units": 0,
  "active_workbench": "PartDesign",
  "active_object_id": "Body001",
  "selection": [
    {
      "object_name": "Body001",
      "subelements": ["Edge3"]
    }
  ],
  "parameters": [
    {
      "object_name": "Body001",
      "object_label": "MainBody",
      "name": "Length",
      "type": "App::PropertyLength",
      "value": 50.0
    }
  ],
  "objects": [
    {
      "name": "Body001",
      "label": "MainBody",
      "type_id": "PartDesign::Body",
      "state": [],
      "in_list": ["Sketch001"],
      "out_list": [],
      "parameters": {...},
      "placement": {
        "base": [0, 0, 0]
      },
      "shape": {
        "has_shape": true,
        "is_null": false,
        "shape_type": "Solid",
        "vertex_count": 48,
        "edge_count": 72,
        "face_count": 24,
        "solid_count": 1,
        "area": 15000.0,
        "volume": 125000.0,
        "tiny_edge_count": 0,
        "tiny_face_count": 0,
        "bbox": {"x": 50, "y": 30, "z": 10}
      },
      "sketch": {}
    }
  ],
  "dependency_edges": [
    {"from": "Body001", "to": "Sketch001"}
  ],
  "recompute_errors": [],
  "snapshot_hash": "sha256-hash-here"
}
```

---

## Value Coercion

```python
def _coerce_value(value):
    if value is None:
        return None
    
    if isinstance(value, (str, int, float, bool)):
        return value
    
    if isinstance(value, (list, tuple)):
        return [_coerce_value(item) for item in value]
    
    # FreeCAD quantities with .Value property
    if hasattr(value, "Value"):
        return value.Value
    
    # FreeCAD vectors
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return [value.x, value.y, value.z]
    
    return str(value)
```

**Purpose:** Convert FreeCAD-specific types to JSON-serializable formats.

---

## Selection-Only Mode

When `selection_only=True`:

1. Get selected object names
2. Expand to include:
   - Objects the selection depends on (InList)
   - Objects that depend on the selection (OutList)
3. Extract only this subset

**Use Cases:**
- Focused validation on specific feature
- Faster iteration during editing
- Reduced token usage for AI calls

---

## Performance Considerations

| Optimization | Implementation |
|--------------|----------------|
| **Limit object count** | AI receives only first 20 objects |
| **Limit issues** | AI receives only first 10 issues |
| **Selection-only mode** | Extract subset when possible |
| **Hash caching** | Skip validation if hash unchanged |
| **Debounced extraction** | 700ms debounce on document changes |

---

## Error Handling

All extraction functions use try/except to gracefully handle:
- Null shapes
- Deleted objects
- Invalid geometry
- Missing properties

**Design Decision:** Return partial data rather than failing completely.

---

## Related Documents

- `02_data_flow.md` - How snapshot flows through system
- `04_validators.md` - How validators use snapshot data
- `05_ai_integration.md` - How AI receives and uses snapshot
