# Tool Registry

## Purpose

The Tool Registry defines and implements all CAD operations that the AI can request. These are the "tools" exposed to the LLM via function calling.

---

## File Location

```
src/Mod/MagicCADAI/ToolRegistry.py
```

---

## Design Principles

1. **Whitelisted Operations Only**: AI cannot execute arbitrary code
2. **Read-Only vs Mutating**: Read-only tools auto-execute; mutating tools require approval
3. **Transaction-Wrapped**: All changes are undoable
4. **Schema-Validated**: Operation parameters validated before execution

---

## Tool Categories

| Category | Tools | Auto-Execute |
|----------|-------|--------------|
| **Read-Only** | `get_document_snapshot`, `get_object_details` | ✅ Yes |
| **Mutating** | `create_body`, `fillet`, `pad`, `set_parameter`, etc. | ❌ No (requires approval) |

---

## Main Entry Point

```python
def execute_tool_request(tool_request, document=None):
    """
    Execute a tool requested by the AI.
    
    Args:
        tool_request: Dict with tool_name and arguments
        document: FreeCAD document (default: ActiveDocument)
    
    Returns:
        Dict with ok (bool), result/error, and operation-specific data
    """
    tool_name = tool_request.get("tool_name", "")
    arguments = tool_request.get("arguments", {})
    
    if tool_name == "get_object_details":
        return get_object_details(
            document=document, 
            object_name=arguments.get("object_name", "")
        )
    
    if tool_name == "get_document_snapshot":
        import Snapshot
        return _success(snapshot=Snapshot.build_document_snapshot(
            document=document, 
            selection_only=arguments.get("selection_only", False)
        ))
    
    if tool_name == "apply_ops":
        return apply_ops(
            arguments.get("ops", []), 
            document=document
        )
    
    return _failure("Unsupported tool request '{0}'".format(tool_name))
```

---

## Read-Only Tools

### get_object_details

```python
def get_object_details(document=None, object_name=""):
    import Snapshot
    
    document = _document(document)
    if document is None:
        return _failure("No active document")
    
    obj = document.getObject(object_name)
    if obj is None:
        return _failure("Object '{0}' was not found".format(object_name))
    
    return _success(object=Snapshot.summarize_object(obj))
```

**Returns:**
```json
{
  "ok": true,
  "object": {
    "name": "Body001",
    "label": "MainBody",
    "type_id": "PartDesign::Body",
    "shape": {...},
    "parameters": {...}
  }
}
```

---

### get_document_snapshot

```python
def get_document_snapshot(document=None, selection_only=False):
    import Snapshot
    return _success(snapshot=Snapshot.build_document_snapshot(
        document=document, 
        selection_only=selection_only
    ))
```

**Returns:** Full `DocumentSnapshot` (see `03_snapshot_extraction.md`)

---

## Mutating Operations

### apply_ops (Main Entry Point)

```python
def apply_ops(ops, document=None, transaction_name="MagicCAD AI Draft"):
    """
    Apply a list of operations to the document.
    
    Args:
        ops: List of operation dicts
        document: FreeCAD document
        transaction_name: Name for undo stack
    
    Returns:
        Dict with ok, results list, and error if failed
    """
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
```

**Key Features:**
- Wrapped in transaction (undoable)
- Recomputes after all operations
- Rolls back on any failure
- Returns detailed results

---

### _apply_operation (Dispatcher)

```python
def _apply_operation(document, op):
    """Dispatch to specific operation handler."""
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
    
    # ... other operations
    
    return _failure("Unsupported operation '{0}'".format(op_name))
```

---

## Operation Implementations

### create_involute_gear

```python
def _create_involute_gear(document, op):
    import InvoluteGearFeature
    
    name = op.get("name", "InvoluteGear")
    profile_name = op.get("profile_name", "{0}Profile".format(name))
    thickness = float(op.get("thickness", 0.0) or 0.0)
    bore = float(op.get("center_bore", 0.0) or 0.0)
    
    # Create gear profile
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
    
    # Extrude if thickness specified
    if thickness > 0.0:
        extrusion = document.addObject("Part::Extrusion", name)
        extrusion.Base = profile
        extrusion.Dir = FreeCAD.Vector(0, 0, thickness)
        extrusion.Solid = True
        created.append(extrusion.Name)
        result = extrusion
        
        # Hide profile
        try:
            profile.ViewObject.Visibility = False
        except Exception:
            pass
        
        # Cut center bore if specified
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
```

**Operation Schema:**
```json
{
  "op": "create_involute_gear",
  "name": "InvoluteGear001",
  "number_of_teeth": 20,
  "module": 2.0,
  "pressure_angle": 20.0,
  "thickness": 10.0,
  "center_bore": 8.0,
  "external_gear": true
}
```

---

### create_body

```python
def _create_body(document, op):
    name = op.get("name", "Body")
    body = document.addObject("PartDesign::Body", name)
    return _success(created=[body.Name], result_object=body.Name)
```

**Operation Schema:**
```json
{
  "op": "create_body",
  "name": "Body002"
}
```

---

### rename_object

```python
def _rename_object(document, op):
    object_name = op.get("object_name", "")
    new_label = op.get("new_label", "")
    
    obj = document.getObject(object_name)
    if obj is None:
        return _failure("Object '{0}' was not found".format(object_name))
    
    obj.Label = new_label
    return _success(updated=[obj.Name], result_object=obj.Name)
```

**Operation Schema:**
```json
{
  "op": "rename_object",
  "object_name": "Body001",
  "new_label": "MainHousing"
}
```

---

### set_parameter

```python
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
        return _failure("Failed to set {0}.{1}: {2}".format(
            object_name, property_name, exc
        ))
    
    return _success(updated=[obj.Name], result_object=obj.Name)
```

**Operation Schema:**
```json
{
  "op": "set_parameter",
  "object_name": "Pad001",
  "property_name": "Length",
  "value": 50.0
}
```

---

### recompute

```python
def _recompute(document, op):
    document.recompute()
    return _success(result_object=document.Name)
```

**Operation Schema:**
```json
{
  "op": "recompute"
}
```

---

## Planned Operations (In plan.md)

These are defined in the architecture but may not all be implemented:

```python
ALLOWED_OPS = [
    "create_body",
    "create_sketch",
    "add_line",
    "add_circle",
    "add_rectangle",
    "pad",
    "pocket",
    "fillet",
    "chamfer",
    "boolean_union",
    "boolean_cut",
    "set_parameter",
    "rename_object",
    "recompute",
]
```

---

## Helper Functions

### _document

```python
def _document(document=None):
    """Get document, defaulting to ActiveDocument."""
    return document or FreeCAD.ActiveDocument
```

---

### _success / _failure

```python
def _success(**payload):
    payload["ok"] = True
    return payload

def _failure(message, **payload):
    payload["ok"] = False
    payload["error"] = message
    return payload
```

---

### _coerce_quantity

```python
def _coerce_quantity(value, unit_suffix):
    """Convert numeric value to FreeCAD quantity string."""
    if isinstance(value, (int, float)):
        return "{0} {1}".format(value, unit_suffix)
    return value
```

**Usage:**
```python
profile.Modules = _coerce_quantity(op["module"], "mm")
# Result: "2.0 mm"
```

---

## Response Structure

### Success

```json
{
  "ok": true,
  "created": ["Body001", "Sketch001"],
  "result_object": "Body001"
}
```

### Failure

```json
{
  "ok": false,
  "error": "Object 'Body999' was not found",
  "results": [...]
}
```

---

## Transaction Handling

```python
document.openTransaction("MagicCAD AI Draft")
try:
    # Execute operations
    document.recompute()
    document.commitTransaction()
except Exception:
    document.abortTransaction()
    raise
```

**Benefits:**
- Single undo step for all AI changes
- Atomic: all succeed or all fail
- Clear labeling in undo stack

---

## Error Handling

```python
try:
    setattr(obj, property_name, value)
except Exception as exc:
    return _failure("Failed to set {0}.{1}: {2}".format(
        object_name, property_name, exc
    ))
```

**Error Types:**
- Object not found
- Property doesn't exist
- Invalid value type
- Constraint violation
- Topological naming issues

---

## Security Considerations

1. **No Arbitrary Code Execution**: AI cannot run arbitrary Python
2. **Whitelisted Operations**: Only predefined ops allowed
3. **Schema Validation**: Parameters validated against expected types
4. **Human Approval**: Mutating ops require approval before execution
5. **Transaction Wrapping**: All changes undoable

---

## Extending the Tool Registry

To add a new operation:

### Step 1: Implement the Handler

```python
def _my_new_operation(document, op):
    # Validate parameters
    object_name = op.get("object_name", "")
    obj = document.getObject(object_name)
    if obj is None:
        return _failure("Object not found")
    
    # Execute operation
    # ...
    
    return _success(created=[new_obj.Name], result_object=new_obj.Name)
```

### Step 2: Add to Dispatcher

```python
def _apply_operation(document, op):
    op_name = op.get("op", "")
    
    # ... existing handlers
    
    if op_name == "my_new_operation":
        return _my_new_operation(document, op)
    
    return _failure("Unsupported operation")
```

### Step 3: Update Tool Specs (SidecarServer.py)

```python
MUTATING_TOOL_SPECS = [
    {
        "type": "function",
        "name": "apply_ops",
        "description": "Apply mutating operations to the document.",
        "parameters": {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["...", "my_new_operation"]},
                            # ... other params
                        }
                    }
                }
            }
        }
    }
]
```

---

## Related Documents

- `07_approval_system.md` - How mutating ops are approved
- `02_data_flow.md` - Tool execution in data flow
- `05_ai_integration.md` - How AI requests tools
