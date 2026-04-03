# Approval System

## Purpose

The Approval System ensures that **no AI-proposed changes are applied to the CAD model without explicit human approval**. This is a critical safety mechanism.

---

## File Locations

| File | Component |
|------|-----------|
| `SidecarServer.py` | `approval_gate()` node, interrupt handling |
| `DockPanel.py` | Approval UI, user interaction |
| `BridgeClient.py` | Resume API calls |

---

## Design Principles

1. **Human-in-the-Loop**: All mutating operations require approval
2. **Interrupt-Driven**: LangGraph pauses at approval gate
3. **Three Options**: Approve, Edit (with feedback), Reject
4. **Audit Trail**: All decisions logged in run history

---

## Approval Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  LangGraph: draft_plan node                                 │
│  - AI proposes changes                                      │
│  - proposed_changes = [...]                                 │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│  LangGraph: approval_gate node                              │
│  - Checks if proposed_changes exists                        │
│  - If yes: triggers interrupt                               │
│  - Graph execution PAUSES                                   │
└─────────────────────────────────────────────────────────────┘
    ↓ SSE: approval_required
┌─────────────────────────────────────────────────────────────┐
│  FreeCAD UI: DockPanel                                      │
│  - Shows approval dialog                                    │
│  - Displays:                                                │
│    - Change summary                                         │
│    - Risk level                                             │
│    - Operations list                                        │
│  - User clicks: Approve | Edit | Reject                     │
└─────────────────────────────────────────────────────────────┘
    ↓ HTTP POST /v1/runs/{run_id}/resume
┌─────────────────────────────────────────────────────────────┐
│  Sidecar: resume_run()                                      │
│  - Calls engine.resume_approval()                           │
│  - LangGraph resumes from interrupt                         │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│  Decision Processing                                        │
│                                                             │
│  If "approve":                                              │
│    → tool_dispatch node executes operations                 │
│    → Changes applied to FreeCAD                             │
│                                                             │
│  If "edit":                                                 │
│    → draft_plan node revises with feedback                  │
│    → Back to approval_gate                                  │
│                                                             │
│  If "reject":                                               │
│    → report_render node (no changes applied)                │
└─────────────────────────────────────────────────────────────┘
```

---

## Sidecar Implementation

### approval_gate Node

```python
def approval_gate(self, state):
    """
    Pause for human approval before applying changes.
    
    Args:
        state: Current graph state
    
    Returns:
        Updated state with approval decision
    """
    proposed_changes = state.get("proposed_changes", [])
    if not proposed_changes:
        return {"approval_status": "not_required"}
    
    run = self.current_run
    if run is None:
        return {"approval_status": "rejected"}
    
    # Set status and publish approval request
    self._set_status(run, "awaiting_approval")
    request = {
        "interrupt_kind": "approval",
        "message": "Approval is required before MagicCAD AI applies local document changes.",
        "proposed_changes": proposed_changes,
    }
    self._publish(run, "approval_required", **request)
    
    # TRIGGER INTERRUPT - Graph pauses here
    decision_payload = self._langgraph.interrupt(request)
    
    self._set_status(run, "running")
    
    # Process decision
    payload = _field(decision_payload, "payload", {}) or {}
    
    if decision == "edit":
        feedback = payload.get("feedback", "")
        self._publish(run, "assistant_delta", 
                     text="Revising the proposed draft based on the latest feedback.", 
                     phase="approval")
        return {
            "approval_status": "edited",
            "approval_feedback": feedback,
        }
    
    if decision == "approve":
        selected = self._select_change(proposed_changes, payload.get("change_id", ""))
        request_id = uuid.uuid4().hex
        
        return {
            "approval_status": "approved",
            "applied_change": selected,
            "pending_tool_request": {
                "request_id": request_id,
                "tool_name": "apply_ops",
                "arguments": {"ops": selected.get("ops", [])},
                "interrupt_kind": "tool",
            },
            "tool_return_to": "report_render",
        }
    
    # Reject
    return {"approval_status": "rejected"}
```

---

### Resume Approval (Sidecar)

```python
def resume_approval(self, run, decision, payload):
    """
    Resume graph execution after human approval decision.
    
    Args:
        run: RunRecord to resume
        decision: "approve", "edit", or "reject"
        payload: Optional feedback or change_id
    """
    if self._langgraph.available:
        # Use LangGraph resume
        self._drive_graph(run, mode="resume", 
                         resume_payload={"decision": decision, "payload": payload or {}})
        return
    
    # Fallback without LangGraph
    run.pending_decision = decision
    run.pending_decision_payload = payload or {}
    run.approval_event.set()  # Unblock waiting thread
    self._persist(run)
```

---

### Server API Endpoint

```python
def do_POST(self):
    parsed = urlparse(self.path)
    parts = [part for part in parsed.path.split("/") if part]
    
    # POST /v1/runs/{run_id}/resume
    if (len(parts) == 4 and parts[0] == "v1" and 
        parts[1] == "runs" and parts[3] == "resume"):
        
        body = self._read_json_body()
        try:
            response = self.server.state.resume_run(
                parts[2], 
                body.get("decision", "reject"), 
                body.get("payload", {})
            )
        except KeyError:
            self._send_json(404, {"ok": False, "error": "Run not found"})
            return
        
        self._send_json(200, response)
        return
```

---

## FreeCAD UI Implementation

### DockPanel: Show Approval Dialog

```python
def _show_approval_dialog(self, proposed_changes):
    """Display approval options to user."""
    # Store changes for later
    self._pending_changes = proposed_changes
    
    # Update UI to show approval pending
    self._widget.set_status("Approval required: Review proposed changes")
    
    # Enable approval buttons in Report tab
    self._widget.apply_button.setEnabled(True)
    self._widget.reject_button.setEnabled(True)
    self._widget.revise_button.setEnabled(True)
    
    # Display change summary
    summary = "\n".join(change.get("summary", "") for change in proposed_changes)
    self._widget.report_browser.setHtml(f"""
        <h3>Proposed Changes</h3>
        <p>{summary}</p>
        <p><i>Click 'Apply Draft' to approve, 'Reject Draft' to discard, 
        or 'Revise Draft' to request changes.</i></p>
    """)
```

---

### Apply Draft (Approve)

```python
def apply_pending_draft(self):
    """User clicked Approve - apply the proposed changes."""
    if not self._pending_changes:
        self._set_status("No pending changes to apply")
        return
    
    # Get selected change (for now, use first)
    change = self._pending_changes[0]
    
    # Resume run with "approve" decision
    response = self._bridge.resume_run(
        self._current_run_id,
        "approve",
        {"change_id": change.get("change_id", "")}
    )
    
    if response and response.get("ok"):
        self._set_status("Applying changes...")
    else:
        self._set_status("Failed to apply changes")
```

---

### Reject Draft

```python
def reject_pending_draft(self):
    """User clicked Reject - discard proposed changes."""
    if not self._pending_changes:
        return
    
    response = self._bridge.resume_run(
        self._current_run_id,
        "reject",
        {}
    )
    
    if response and response.get("ok"):
        self._set_status("Changes rejected")
        self._pending_changes = None
    else:
        self._set_status("Failed to reject changes")
```

---

### Revise Draft (Edit)

```python
def revise_pending_draft(self):
    """User clicked Edit - provide feedback for revision."""
    if not self._pending_changes:
        return
    
    # Get feedback from prompt input
    feedback = self._widget.current_prompt()
    if not feedback:
        self._set_status("Enter revision feedback in the copilot box before revising the draft")
        return
    
    response = self._bridge.resume_run(
        self._current_run_id,
        "edit",
        {"feedback": feedback}
    )
    
    if response and response.get("ok"):
        self._set_status("Revision feedback sent to the sidecar")
    else:
        self._set_status("Failed to send revision feedback")
```

---

## ProposedChange Structure

```json
{
  "change_id": "uuid-here",
  "summary": "Add 5mm fillet to Edge3 on Body001",
  "risk_level": "low",
  "ops": [
    {
      "op": "fillet",
      "object_name": "Body001",
      "edges": ["Edge3"],
      "radius": 5.0
    },
    {
      "op": "recompute"
    }
  ]
}
```

### Risk Levels

| Level | Description | Examples |
|-------|-------------|----------|
| `low` | Safe, reversible changes | Rename, add fillet, adjust parameter |
| `medium` | May affect downstream features | Add feature, boolean operations |
| `high` | Potentially destructive | Delete feature, major geometry change |

---

## Decision Options

### Approve

```json
{
  "decision": "approve",
  "payload": {
    "change_id": "abc123"
  }
}
```

**Flow:**
1. Graph resumes
2. `tool_dispatch` node executes `apply_ops`
3. Changes applied to FreeCAD
4. Model recomputed
5. Re-validation runs

---

### Edit

```json
{
  "decision": "edit",
  "payload": {
    "feedback": "Make the fillet 3mm instead of 5mm"
  }
}
```

**Flow:**
1. Graph resumes
2. `draft_plan` node revises changes with feedback
3. New proposed changes generated
4. Back to `approval_gate`
5. User reviews revised changes

---

### Reject

```json
{
  "decision": "reject",
  "payload": {}
}
```

**Flow:**
1. Graph resumes
2. `report_render` node generates report (no changes)
3. Run completes
4. Model unchanged

---

## Fallback Implementation (Without LangGraph)

```python
def _approval_loop(self, run, state):
    """Approval loop for non-LangGraph fallback."""
    proposed_changes = list(state.get("proposed_changes", []))
    
    while proposed_changes:
        self._set_status(run, "awaiting_approval")
        run.approval_event.clear()
        
        # Publish approval request
        self._publish(
            run,
            "approval_required",
            proposed_changes=proposed_changes,
            message="Approval is required before MagicCAD AI applies local document changes.",
            interrupt_kind="approval",
        )
        
        # Wait for decision (blocking)
        run.approval_event.wait()
        
        decision = run.pending_decision or "reject"
        payload = run.pending_decision_payload or {}
        run.pending_decision = None
        run.pending_decision_payload = {}
        
        self._set_status(run, "running")
        
        if decision == "reject":
            state["approval_status"] = "rejected"
            state["proposed_changes"] = proposed_changes
            return state
        
        if decision == "edit":
            proposed_changes = PromptInterpreter.revise_changes(
                proposed_changes, 
                payload.get("feedback", "")
            )
            state["proposed_changes"] = proposed_changes
            state["approval_status"] = "edited"
            continue
        
        # Approve: execute changes
        selected = self._select_change(proposed_changes, payload.get("change_id", ""))
        run.tool_result_event.clear()
        
        self._set_status(run, "awaiting_tool")
        self._publish(
            run,
            "tool_request",
            request_id=uuid.uuid4().hex,
            tool_name="apply_ops",
            arguments={"ops": selected.get("ops", [])},
            interrupt_kind="tool",
            return_node="report_render",
        )
        
        run.tool_result_event.wait()
        tool_result = run.pending_tool_result or {"result": {"ok": False}}
        run.pending_tool_result = None
        
        self._set_status(run, "running")
        state.setdefault("tool_results", []).append(tool_result)
        state["approval_status"] = "approved" if tool_result["result"]["ok"] else "failed"
        
        return state
    
    return state
```

---

## SSE Event: approval_required

```json
{
  "event": "approval_required",
  "run_id": "run-abc123",
  "thread_id": "thread-xyz789",
  "interrupt_kind": "approval",
  "message": "Approval is required before MagicCAD AI applies local document changes.",
  "proposed_changes": [
    {
      "change_id": "change-001",
      "summary": "Add 5mm fillet to Edge3",
      "risk_level": "low",
      "ops": [...]
    }
  ]
}
```

---

## State Transitions

```
draft_plan (proposed_changes = [...])
    ↓
approval_gate
    ↓
[INTERRUPT - Graph Pauses]
    ↓
[User Decision]
    ↓
┌─────────────┬─────────────┬─────────────┐
│   Approve   │    Edit     │   Reject    │
└──────┬──────┴──────┬──────┴──────┬──────┘
       │             │             │
       ↓             ↓             ↓
  tool_dispatch  draft_plan   report_render
       ↓             ↓             ↓
  (apply ops)   (revise)      (no changes)
       ↓             ↓             ↓
  report_render  approval_gate  complete
       ↓             ↓
  complete      (loop)
```

---

## Error Handling

### Timeout

If user doesn't respond, the run remains in `awaiting_approval` state. The UI should show:
- Current status
- Pending changes
- Option to cancel

### Sidecar Crash

- Run state persisted in SQLite
- On restart, can resume from approval gate
- UI reconstructs pending changes from state

### Invalid Decision

```python
if decision not in ("approve", "edit", "reject"):
    decision = "reject"  # Default to safe option
```

---

## Security Considerations

1. **No Auto-Execute**: Mutating ops never auto-execute
2. **Explicit Decision**: User must click a button
3. **Change Preview**: Summary shown before approval
4. **Risk Indication**: Risk level displayed
5. **Undo Available**: Changes wrapped in transaction

---

## Related Documents

- `06_tool_registry.md` - Operations that require approval
- `05_ai_integration.md` - LangGraph interrupt mechanism
- `02_data_flow.md` - Approval in data flow
- `11_langgraph_workflow.md` - Graph node details
