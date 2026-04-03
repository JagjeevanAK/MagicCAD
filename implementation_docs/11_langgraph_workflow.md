# LangGraph Workflow

## Purpose

This document describes the LangGraph StateGraph workflow that orchestrates the AI validation process.

---

## File Location

```
src/Mod/MagicCADAI/SidecarServer.py
```

**Classes:**
- `LangGraphRuntime` - Graph compilation and execution
- `MagicCADAgentEngine` - Node implementations and routing

---

## Graph Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph StateGraph                         │
│                                                                 │
│  [START]                                                        │
│     ↓                                                           │
│  ┌─────────────────┐                                           │
│  │    intake       │                                           │
│  └────────┬────────┘                                           │
│           ↓                                                     │
│  ┌─────────────────┐                                           │
│  │ normalize_      │                                           │
│  │   snapshot      │                                           │
│  └────────┬────────┘                                           │
│           ↓                                                     │
│  ┌─────────────────┐                                           │
│  │ deterministic_  │                                           │
│  │   validate      │                                           │
│  └────────┬────────┘                                           │
│           ↓                                                     │
│  ┌─────────────────┐                                           │
│  │   llm_explain   │───(tool requested)───┐                    │
│  └────────┬────────┘                      │                    │
│           │ (no tool)                      │                    │
│           ↓                                 ↓                    │
│  ┌─────────────────┐              ┌─────────────────┐          │
│  │   draft_plan    │              │  tool_dispatch  │          │
│  └────────┬────────┘              └────────┬────────┘          │
│           │                                │                    │
│           ├────(changes proposed)──────────┤                    │
│           │                                │                    │
│           ↓                                │                    │
│  ┌─────────────────┐                      │                    │
│  │  approval_gate  │◄─────────────────────┘                    │
│  └────────┬────────┘                                           │
│           │                                                     │
│           ├────(edited)────────────────┐                        │
│           │                             │                       │
│           ├────(tool requested)─────────┼───┐                   │
│           │                             │   │                   │
│           ↓                             │   │                   │
│  ┌─────────────────┐                    │   │                   │
│  │  report_render  │◄───────────────────┴───┘                   │
│  └────────┬────────┘                                           │
│           ↓                                                     │
│  ┌─────────────────┐                                           │
│  │    complete     │                                           │
│  └────────┬────────┘                                           │
│           ↓                                                     │
│         [END]                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Graph Compilation

```python
from langgraph.graph import END, START, StateGraph

class LangGraphRuntime:
    def __init__(self, engine, database_path):
        self._engine = engine
        self.available = False
        self.error = ""
        self._compiled = None
        
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            from langgraph.graph import END, START, StateGraph
            from langgraph.types import Command, interrupt
        except Exception as exc:
            self.error = str(exc)
            return
        
        # Initialize checkpointer
        try:
            self._checkpointer = SqliteSaver.from_conn_string(database_path)
        except Exception:
            try:
                self._checkpointer = SqliteSaver(
                    sqlite3.connect(database_path, check_same_thread=False)
                )
            except Exception as exc:
                self.error = str(exc)
                return
        
        # Build graph
        graph = StateGraph(dict)
        
        # Add nodes
        graph.add_node("intake", self._wrap("intake", engine.intake))
        graph.add_node("normalize_snapshot", 
                      self._wrap("normalize_snapshot", engine.normalize_snapshot))
        graph.add_node("deterministic_validate", 
                      self._wrap("deterministic_validate", engine.deterministic_validate))
        graph.add_node("llm_explain", self._wrap("llm_explain", engine.llm_explain))
        graph.add_node("draft_plan", self._wrap("draft_plan", engine.draft_plan))
        graph.add_node("approval_gate", self._wrap("approval_gate", engine.approval_gate))
        graph.add_node("tool_dispatch", self._wrap("tool_dispatch", engine.tool_dispatch))
        graph.add_node("report_render", self._wrap("report_render", engine.report_render))
        graph.add_node("complete", self._wrap("complete", engine.complete))
        
        # Add edges
        graph.add_edge(START, "intake")
        graph.add_edge("intake", "normalize_snapshot")
        graph.add_edge("normalize_snapshot", "deterministic_validate")
        graph.add_edge("deterministic_validate", "llm_explain")
        
        # Conditional edges
        graph.add_conditional_edges(
            "llm_explain",
            engine.route_after_llm_explain,
            {"draft_plan": "draft_plan", "tool_dispatch": "tool_dispatch"},
        )
        
        graph.add_conditional_edges(
            "draft_plan",
            engine.route_after_draft_plan,
            {
                "approval_gate": "approval_gate",
                "tool_dispatch": "tool_dispatch",
                "report_render": "report_render",
            },
        )
        
        graph.add_conditional_edges(
            "approval_gate",
            engine.route_after_approval_gate,
            {
                "draft_plan": "draft_plan",
                "tool_dispatch": "tool_dispatch",
                "report_render": "report_render",
            },
        )
        
        graph.add_conditional_edges(
            "tool_dispatch",
            engine.route_after_tool_dispatch,
            {
                "llm_explain": "llm_explain",
                "draft_plan": "draft_plan",
                "report_render": "report_render",
            },
        )
        
        graph.add_edge("report_render", "complete")
        graph.add_edge("complete", END)
        
        # Compile with checkpointer
        try:
            self._compiled = graph.compile(checkpointer=self._checkpointer)
            self._command_cls = Command
            self._interrupt_fn = interrupt
            self.available = True
        except Exception as exc:
            self.error = str(exc)
            self._compiled = None
```

---

## Node Implementations

### intake

```python
def intake(self, state):
    """Initialize the run."""
    summary = "Intake complete for {0} objects.".format(
        len(state.get("snapshot", {}).get("objects", []))
    )
    return {"assistant_phase": "intake", "summary": summary}
```

**Input:**
```python
{
    "snapshot": {"objects": [...]},
    "prompt": "...",
    ...
}
```

**Output:**
```python
{
    "assistant_phase": "intake",
    "summary": "Intake complete for 5 objects."
}
```

---

### normalize_snapshot

```python
def normalize_snapshot(self, state):
    """Ensure snapshot has all required fields."""
    snapshot = dict(state.get("snapshot", {}) or {})
    snapshot.setdefault("objects", [])
    snapshot.setdefault("selection", [])
    snapshot.setdefault("dependency_edges", [])
    snapshot.setdefault("recompute_errors", [])
    
    return {"assistant_phase": "normalize_snapshot", "snapshot": snapshot}
```

**Purpose:** Validate and normalize snapshot structure.

---

### deterministic_validate

```python
def deterministic_validate(self, state):
    """Run rule-based validators."""
    import Validators
    
    issues = Validators.validate_snapshot(state.get("snapshot", {}))
    
    run = self.current_run
    if run is not None:
        self._publish(run, "issues_delta", issues=issues)
    
    return {
        "assistant_phase": "deterministic_validate",
        "issues": issues,
        "issue_counts": Validators.issue_counts(issues),
    }
```

**Output:**
```python
{
    "assistant_phase": "deterministic_validate",
    "issues": [...],
    "issue_counts": {"total": 3, "high": 1, "medium": 2}
}
```

---

### llm_explain

```python
def llm_explain(self, state):
    """Call OpenAI API for explanation."""
    explanation = self._llm.explain(state)
    text = explanation.get("assistant_text", "")
    
    # Fallback if AI fails
    if not text:
        text = self._fallback_explanation(
            state.get("snapshot", {}),
            state.get("issues", []),
            state.get("prompt", "")
        )
    
    run = self.current_run
    if run is not None and text:
        self._publish(run, "assistant_delta", text=text, 
                     phase=explanation.get("assistant_phase", "llm_explain"))
    
    return {
        "assistant_phase": explanation.get("assistant_phase", "llm_explain"),
        "assistant_text": text,
        "previous_response_id": explanation.get("previous_response_id", ""),
        "pending_tool_request": explanation.get("pending_tool_request"),
        "tool_return_to": explanation.get("tool_return_to", ""),
        "backend": {
            "openai": self._llm.available,
            "langgraph": self._langgraph.available,
            "model": state.get("model", DEFAULT_MODEL),
        },
    }
```

**Output:**
```python
{
    "assistant_phase": "validate",
    "assistant_text": "I found 3 issues...",
    "previous_response_id": "resp-abc123",
    "pending_tool_request": None,
    "tool_return_to": ""
}
```

---

### draft_plan

```python
def draft_plan(self, state):
    """Generate proposed changes."""
    feedback = (state.get("approval_feedback", "") or "").strip()
    proposed_changes = state.get("proposed_changes", [])
    
    if feedback and proposed_changes:
        # Revise based on feedback
        changes = PromptInterpreter.revise_changes(proposed_changes, feedback)
    else:
        # Generate new plan from prompt
        changes = PromptInterpreter.plan_changes(
            state.get("snapshot", {}),
            state.get("prompt", ""),
            state.get("issues", []),
        )
    
    return {
        "assistant_phase": "draft_plan",
        "proposed_changes": changes,
        "approval_status": "required" if changes else "not_required",
        "approval_feedback": "",
    }
```

**Output:**
```python
{
    "assistant_phase": "draft_plan",
    "proposed_changes": [
        {
            "change_id": "change-001",
            "summary": "Add 5mm fillet to Edge3",
            "risk_level": "low",
            "ops": [...]
        }
    ],
    "approval_status": "required"
}
```

---

### approval_gate

See `07_approval_system.md` for full implementation.

```python
def approval_gate(self, state):
    """Pause for human approval."""
    proposed_changes = state.get("proposed_changes", [])
    if not proposed_changes:
        return {"approval_status": "not_required"}
    
    # Trigger interrupt (pauses graph)
    decision_payload = self._langgraph.interrupt(request)
    
    # Process decision (approve/edit/reject)
    # ...
```

---

### tool_dispatch

```python
def tool_dispatch(self, state):
    """Execute tool requested by AI."""
    tool_request = state.get("pending_tool_request")
    if not tool_request:
        return {"tool_return_to": ""}
    
    run = self.current_run
    if run is None:
        return {
            "pending_tool_request": None,
            "tool_return_to": "",
            "tool_results": list(state.get("tool_results", [])),
        }
    
    # Publish tool request event
    request = dict(tool_request)
    request.setdefault("interrupt_kind", "tool")
    self._publish(run, "tool_request", **request)
    
    # Trigger interrupt (wait for tool execution)
    tool_result = self._langgraph.interrupt(request)
    
    # Collect results
    collected = list(state.get("tool_results", []))
    collected.append(tool_result or {"result": {"ok": False}})
    
    return {
        "pending_tool_request": None,
        "tool_results": collected,
    }
```

---

### report_render

```python
def report_render(self, state):
    """Generate final report."""
    return {
        "assistant_phase": "report_render",
        "report": self._render_report(state),
    }
```

---

### complete

```python
def complete(self, state):
    """Terminal node."""
    return {"assistant_phase": "complete"}
```

---

## Routing Logic

### route_after_llm_explain

```python
def route_after_llm_explain(self, state):
    """Route after LLM explanation."""
    if state.get("pending_tool_request"):
        return "tool_dispatch"
    return "draft_plan"
```

**Logic:**
- If AI requested a tool → `tool_dispatch`
- Otherwise → `draft_plan`

---

### route_after_draft_plan

```python
def route_after_draft_plan(self, state):
    """Route after draft plan generation."""
    if state.get("pending_tool_request"):
        return "tool_dispatch"
    if state.get("proposed_changes"):
        return "approval_gate"
    return "report_render"
```

**Logic:**
- If tool requested → `tool_dispatch`
- If changes proposed → `approval_gate`
- Otherwise → `report_render`

---

### route_after_approval_gate

```python
def route_after_approval_gate(self, state):
    """Route after approval decision."""
    if state.get("approval_status") == "edited":
        return "draft_plan"  # Revise and re-approve
    if state.get("pending_tool_request"):
        return "tool_dispatch"  # Execute approved changes
    return "report_render"  # No changes, generate report
```

**Logic:**
- If edited → back to `draft_plan`
- If approved with tool → `tool_dispatch`
- Otherwise → `report_render`

---

### route_after_tool_dispatch

```python
def route_after_tool_dispatch(self, state):
    """Route after tool execution."""
    return state.get("tool_return_to", "") or "report_render"
```

**Logic:**
- Return to the node specified in `tool_return_to`
- Default → `report_render`

---

## Graph Invocation

### Initial Invoke

```python
def _drive_graph(self, run, mode="start", resume_payload=None):
    self._local.run = run
    config = {"configurable": {"thread_id": run.thread_id}}
    
    if mode == "start":
        run.status = "running"
        self._persist(run)
        self._publish(run, "run_started", status="running")
        
        # Initial graph execution
        result = self._langgraph.initial_invoke(dict(run.state), config)
    else:
        # Resume after interrupt
        run.status = "running"
        self._persist(run)
        result = self._langgraph.resume_invoke(resume_payload, config)
    
    # Update state from graph result
    graph_state = self._langgraph.current_state(config, result)
    if isinstance(graph_state, dict):
        run.state.update(graph_state)
    
    self._persist(run)
    
    # Check if waiting for user input
    if run.status in ("awaiting_approval", "awaiting_tool"):
        return
    
    # Continue to completion
    # ...
```

---

### Resume After Interrupt

```python
def resume_invoke(self, resume_payload, config):
    """Resume graph after interrupt (approval or tool result)."""
    if not self.available or self._compiled is None or self._command_cls is None:
        return resume_payload
    
    return self._compiled.invoke(
        self._command_cls(resume=resume_payload), 
        config=config
    )
```

**Resume Payload:**
```python
# For approval
{
    "decision": "approve",
    "payload": {"change_id": "change-001"}
}

# For tool result
{
    "result": {"ok": true, "created": ["Body001"]}
}
```

---

## Interrupt Mechanism

### Trigger Interrupt

```python
def interrupt(self, payload):
    """Trigger LangGraph interrupt (pauses graph)."""
    if not self.available or self._interrupt_fn is None:
        raise RuntimeError("LangGraph interrupt is not available")
    return self._interrupt_fn(payload)
```

**Usage in approval_gate:**
```python
request = {
    "interrupt_kind": "approval",
    "message": "Approval is required...",
    "proposed_changes": proposed_changes,
}
decision_payload = self._langgraph.interrupt(request)
# Graph pauses here until resume
```

---

### Interrupt Types

| Type | Triggered By | Resumed By |
|------|--------------|------------|
| `approval` | `approval_gate` node | User clicks Approve/Edit/Reject |
| `tool` | `tool_dispatch` node | Tool execution completes |

---

## State Transitions

### Normal Flow (No Changes)

```
START → intake → normalize_snapshot → deterministic_validate 
→ llm_explain → draft_plan → report_render → complete → END
```

---

### With Tool Request

```
START → intake → normalize_snapshot → deterministic_validate 
→ llm_explain → tool_dispatch → [INTERRUPT: tool]
→ (wait for tool result)
→ resume → llm_explain → draft_plan → report_render → complete → END
```

---

### With Approval

```
START → intake → normalize_snapshot → deterministic_validate 
→ llm_explain → draft_plan → approval_gate → [INTERRUPT: approval]
→ (wait for user decision)
→ resume (approve) → tool_dispatch → report_render → complete → END
```

---

### With Revision

```
START → ... → draft_plan → approval_gate → [INTERRUPT: approval]
→ (user clicks Edit with feedback)
→ resume (edit) → draft_plan → approval_gate → [INTERRUPT: approval]
→ (user clicks Approve)
→ resume (approve) → tool_dispatch → report_render → complete → END
```

---

## Error Handling

### Node Execution Error

```python
def _wrap(self, node_name, fn):
    """Wrap node execution with status publishing."""
    def wrapper(state):
        self._engine.publish_node(node_name, "running")
        try:
            updates = fn(state)
            self._engine.publish_node(node_name, "completed")
            return updates
        except Exception as exc:
            self._engine.publish_node(node_name, "error")
            raise
    return wrapper
```

---

### Graph Execution Error

```python
def _drive_graph(self, run, mode="start"):
    try:
        # ... graph execution
    except Exception as exc:
        run.status = "error"
        run.state["error"] = str(exc)
        self._persist(run)
        
        self._publish(run, "run_error", 
                     message=str(exc), 
                     traceback=traceback.format_exc())
        self._publish(run, "run_finished", status="error")
        
        run.close("error")
        self._persist(run)
```

---

## Checkpointing

### SQLite Checkpointer

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string(database_path)
# Database: ~/.local/share/FreeCAD/MagicCADAI/runs.sqlite3
```

**Purpose:**
- Persist graph state between interrupts
- Enable resume after crash/restart
- Maintain conversation history

---

### Get Current State

```python
def current_state(self, config, fallback):
    """Get current graph state from checkpoint."""
    if not self.available or self._compiled is None:
        return fallback
    
    try:
        snapshot = self._compiled.get_state(config)
        values = getattr(snapshot, "values", None)
        if isinstance(values, dict):
            return values
    except Exception:
        pass
    
    return fallback
```

---

## Related Documents

- `05_ai_integration.md` - AI integration overview
- `07_approval_system.md` - Approval interrupt details
- `09_sidecar_server.md` - Sidecar architecture
- `02_data_flow.md` - Data flow through graph
