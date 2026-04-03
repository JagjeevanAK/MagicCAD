# Data Flow Documentation

## Complete Data Flow: User Clicks "Validate Document"

This document traces the complete data flow from user action to AI response and potential model modification.

---

## Flow Diagram

```
User Action
    ↓
┌─────────────────────────────────────────────────────────────┐
│  FreeCAD Module                                             │
│                                                             │
│  1. Commands.py: ValidateDocumentCommand.Activated()        │
│         ↓                                                   │
│  2. DockPanel.py: validate_document()                       │
│         ↓                                                   │
│  3. Snapshot.py: build_document_snapshot()                  │
│         ↓                                                   │
│  4. Validators.py: validate_snapshot()                      │
│         ↓                                                   │
│  5. BridgeClient.py: start_run(payload)                     │
│         ↓                                                   │
│  6. SidecarServer.py: HTTP POST /v1/runs                    │
└─────────────────────────────────────────────────────────────┘
    ↓ HTTP localhost:50173
┌─────────────────────────────────────────────────────────────┐
│  Sidecar Server                                             │
│                                                             │
│  7. ServerState.create_run()                                │
│         ↓                                                   │
│  8. LangGraphRuntime.initial_invoke()                       │
│         ↓                                                   │
│  Graph Execution:                                           │
│  9a. intake()                                               │
│  9b. normalize_snapshot()                                   │
│  9c. deterministic_validate() ← uses cached issues          │
│  9d. llm_explain() → OpenAI API call                        │
│  9e. draft_plan()                                           │
│  9f. approval_gate() (if changes proposed)                  │
│  9g. tool_dispatch() (if tool requested)                    │
│  9h. report_render()                                        │
│  9i. complete()                                             │
│         ↓                                                   │
│  10. SQLiteRunStore.save_run()                              │
│         ↓                                                   │
│  11. SSE events streamed back to UI                         │
└─────────────────────────────────────────────────────────────┘
    ↓ SSE (Server-Sent Events)
┌─────────────────────────────────────────────────────────────┐
│  FreeCAD Module (UI Updates)                                │
│                                                             │
│  12. BridgeClient.eventReceived()                           │
│         ↓                                                   │
│  13. DockPanel.py: _handle_event()                          │
│         ↓                                                   │
│  14. UI Updates:                                            │
│      - transcript.appendPlainText()                         │
│      - set_issues()                                         │
│      - report_browser.setHtml()                             │
│      - status_label.setText()                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Breakdown

### Step 1: User Triggers Validation

**File:** `Commands.py`

```python
class ValidateDocumentCommand(_BaseCommand):
    def Activated(self):
        import DockPanel
        controller = DockPanel.get_controller()
        controller.show_panel()
        controller.validate_document(selection_only=False, intent="validate")
```

**Data:** None yet

---

### Step 2: DockPanel Starts Validation

**File:** `DockPanel.py`

```python
def validate_document(self, selection_only=False, intent="validate"):
    document = FreeCAD.ActiveDocument
    if document is None:
        return
    
    # Build snapshot
    snapshot = Snapshot.build_document_snapshot(
        document=document, 
        selection_only=selection_only
    )
    
    # Prepare payload
    payload = {
        "model": self._widget.current_model(),  # "gpt-5.4"
        "intent": intent,
        "prompt": self._widget.current_prompt(),
        "selection_only": selection_only,
        "snapshot": snapshot,
    }
    
    # Send to sidecar
    response = self._bridge.start_run(payload)
```

**Data Produced:** `DocumentSnapshot` (JSON)

---

### Step 3: Snapshot Extraction

**File:** `Snapshot.py`

```python
def build_document_snapshot(document=None, selection_only=False):
    # Extract selection
    selected_names = _selected_object_names(document)
    
    # Filter objects (exclude internal MagicCAD objects)
    objects = [obj for obj in document.Objects 
               if obj.Name not in internal_names]
    
    # Build snapshot
    snapshot = {
        "document_id": getattr(document, "Uid", document.Name),
        "document_name": document.Name,
        "document_label": document.Label,
        "units": FreeCAD.ParamGet(...).GetInt("UserSchema", 0),
        "active_workbench": FreeCADGui.activeWorkbench().name(),
        "active_object_id": active_object.Name if active_object else "",
        "selection": _selection_refs(document),
        "parameters": _collect_parameters(objects),
        "objects": [summarize_object(obj) for obj in objects],
        "dependency_edges": _collect_dependency_edges(objects),
        "recompute_errors": _collect_recompute_errors(objects),
    }
    
    # Add hash for change detection
    snapshot["snapshot_hash"] = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode()
    ).hexdigest()
    
    return snapshot
```

**Data Produced:** Full `DocumentSnapshot` with all model metadata

---

### Step 4: Run Validators

**File:** `Validators.py`

```python
def validate_snapshot(snapshot):
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

**Data Produced:** `List[ValidationIssue]`

---

### Step 5: Send to Sidecar

**File:** `BridgeClient.py`

```python
def start_run(self, payload):
    if not self.ensure_started():  # Launches sidecar if needed
        return None
    
    response = self._request("POST", "/v1/runs", payload)
    run_id = response.get("run_id", "")
    
    # Start listening for SSE events
    if run_id:
        self._start_event_stream(run_id)
    
    return response
```

**Data Sent:** HTTP POST with snapshot + issues

---

### Step 6: Sidecar Creates Run

**File:** `SidecarServer.py`

```python
def create_run(self, request):
    run = RunRecord(request)  # Creates run with initial state
    self._store.save_run(run)  # Persist to SQLite
    
    # Start graph execution in background thread
    worker = threading.Thread(
        target=self._engine.start_run, 
        args=(run,), 
        daemon=True
    )
    worker.start()
    
    return run
```

**Data Produced:** `RunRecord` with unique `run_id`

---

### Step 7-9: LangGraph Execution

**File:** `SidecarServer.py`

```python
def _drive_graph(self, run, mode="start"):
    config = {"configurable": {"thread_id": run.thread_id}}
    
    if mode == "start":
        result = self._langgraph.initial_invoke(dict(run.state), config)
    else:
        result = self._langgraph.resume_invoke(resume_payload, config)
    
    # Update run state from graph result
    graph_state = self._langgraph.current_state(config, result)
    run.state.update(graph_state)
    self._persist(run)
```

**Graph Nodes Execute:**

| Node | Function | Data Produced |
|------|----------|---------------|
| `intake` | `engine.intake()` | Summary message |
| `normalize_snapshot` | `engine.normalize_snapshot()` | Validated snapshot |
| `deterministic_validate` | `engine.deterministic_validate()` | Issues list |
| `llm_explain` | `engine.llm_explain()` → OpenAI API | AI explanation |
| `draft_plan` | `engine.draft_plan()` | Proposed changes |
| `approval_gate` | `engine.approval_gate()` | Approval decision |
| `tool_dispatch` | `engine.tool_dispatch()` | Tool results |
| `report_render` | `engine.report_render()` | Markdown/HTML report |
| `complete` | `engine.complete()` | Terminal state |

---

### Step 10: OpenAI API Call

**File:** `SidecarServer.py` - `OpenAIResponder.explain()`

```python
def explain(self, state):
    payload = {
        "phase": phase,  # "validate" or "copilot"
        "intent": state.get("intent", "validate"),
        "prompt": state.get("prompt", ""),
        "issue_count": len(issues),
        "issues": issues[:10],
        "objects": snapshot.get("objects", [])[:20],
        "selection": snapshot.get("selection", []),
        "tool_results": state.get("tool_results", [])[-3:],
    }
    
    response = self._client.responses.create(
        model=model,  # "gpt-5.4"
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)},
        ],
        tools=READ_ONLY_TOOL_SPECS,
        previous_response_id=state.get("previous_response_id", ""),
    )
    
    return self._parse_response(response)
```

**Data Sent to OpenAI:** JSON with snapshot summary + issues

**Data Received:** 
- `output_text`: AI explanation
- `output[].function_call`: Optional tool request
- `id`: Response ID for continuity

---

### Step 11: SSE Events Streamed to UI

**File:** `SidecarServer.py` - `_stream_events()`

```python
def _stream_events(self, run):
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    
    index = 0
    while True:
        with run.condition:
            if index >= len(run.events) and not run.terminal:
                run.condition.wait(timeout=1.0)
            if index < len(run.events):
                event = run.events[index]
                index += 1
            elif run.terminal:
                break
        
        # Send SSE event
        payload = json.dumps(event, sort_keys=True)
        self.wfile.write(f"event: {event['event']}\n".encode())
        self.wfile.write(f"data: {payload}\n\n".encode())
```

**Events Streamed:**
```
event: run_started
data: {"run_id": "...", "status": "running"}

event: node_status
data: {"node": "intake", "status": "running"}

event: node_status
data: {"node": "intake", "status": "completed"}

event: assistant_delta
data: {"text": "I found 3 issues...", "phase": "validate"}

event: issues_delta
data: {"issues": [...]}

event: report_ready
data: {"report": {...}}

event: run_finished
data: {"status": "completed"}
```

---

### Step 12-14: UI Updates

**File:** `DockPanel.py`

```python
def _handle_event(self, event):
    event_name = event.get("event", "")
    
    if event_name == "assistant_delta":
        text = event.get("text", "")
        self._widget.append_transcript(text)
    
    elif event_name == "issues_delta":
        issues = event.get("issues", [])
        self._widget.set_issues(issues)
    
    elif event_name == "report_ready":
        report = event.get("report", {})
        self._update_report_display(report)
    
    elif event_name == "approval_required":
        changes = event.get("proposed_changes", [])
        self._show_approval_dialog(changes)
    
    elif event_name == "tool_request":
        tool_request = event.get("request", {})
        self._execute_tool(tool_request)
```

**UI Updates:**
- Transcript panel shows AI explanation
- Issues list populated with validation results
- Report tab shows markdown/HTML report
- Approval dialog appears if changes proposed

---

## Approval Flow (If Changes Proposed)

```
┌─────────────────────────────────────────────────────────────┐
│  User clicks "Apply Draft"                                  │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│  DockPanel.py: apply_pending_draft()                        │
│         ↓                                                   │
│  BridgeClient.resume_run(run_id, "approve", payload)        │
│         ↓                                                   │
│  HTTP POST /v1/runs/{run_id}/resume                         │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│  SidecarServer.py: resume_run()                             │
│         ↓                                                   │
│  engine.resume_approval(run, "approve", payload)            │
│         ↓                                                   │
│  LangGraph resumes from approval_gate node                  │
│         ↓                                                   │
│  tool_dispatch node executes apply_ops                      │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│  ToolRegistry.py: apply_ops()                               │
│         ↓                                                   │
│  document.openTransaction("MagicCAD AI Draft")              │
│         ↓                                                   │
│  For each op: _apply_operation(document, op)                │
│         ↓                                                   │
│  document.recompute()                                       │
│         ↓                                                   │
│  document.commitTransaction()                               │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│  FreeCAD model is modified (undoable)                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Structures Reference

### DocumentSnapshot

```python
{
    "document_id": str,           # UUID or document name
    "document_name": str,         # Internal name
    "document_label": str,        # User-visible label
    "units": int,                 # Unit schema ID
    "active_workbench": str,      # e.g., "PartDesign"
    "active_object_id": str,      # Currently selected object
    "selection": List[Dict],      # Selection refs
    "parameters": List[Dict],     # All parameters
    "objects": List[Dict],        # Object summaries
    "dependency_edges": List[Dict],  # Dependency graph
    "recompute_errors": List[Dict],  # Error states
    "snapshot_hash": str          # SHA256 hash
}
```

### ValidationIssue

```python
{
    "issue_id": str,              # UUID
    "rule_id": str,               # e.g., "null-shape"
    "severity": str,              # critical/high/medium/low
    "category": str,              # geometry/sketch/naming/etc.
    "source": str,                # "deterministic" or "llm"
    "confidence": float,          # 0.0-1.0
    "object_ref": Dict,           # {"object_name": "..."}
    "subelement_ref": Dict,       # {"subelement": "Edge3"}
    "evidence": Dict,             # Supporting data
    "message": str,               # User-visible message
    "recommended_fix": str,       # Suggested action
    "highlight_mode": str         # "object" or "subelement"
}
```

### ProposedChange

```python
{
    "change_id": str,             # UUID
    "summary": str,               # Human-readable summary
    "risk_level": str,            # low/medium/high
    "ops": List[Dict]             # Operations to execute
}
```

### Operation (op)

```python
{
    "op": str,                    # Operation type
    "object_name": str,           # Target object
    # ... operation-specific params
}
```

**Allowed Operations:**
- `create_body`, `create_sketch`, `create_involute_gear`
- `add_line`, `add_circle`, `add_rectangle`
- `pad`, `pocket`, `fillet`, `chamfer`
- `boolean_union`, `boolean_cut`
- `set_parameter`, `rename_object`
- `recompute`

---

## Related Documents

- `01_architecture_overview.md` - System architecture
- `03_snapshot_extraction.md` - Snapshot extraction details
- `05_ai_integration.md` - OpenAI integration
- `07_approval_system.md` - Approval flow details
- `11_langgraph_workflow.md` - LangGraph state machine
