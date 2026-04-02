# Architecture Overview

## System Architecture

MagicCAD AI uses a **two-process architecture**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    FreeCAD GUI (Desktop Application)            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │           MagicCADAI Workbench (Python Module)            │  │
│  │                                                           │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐   │  │
│  │  │   Snapshot   │  │  Validators  │  │  ToolRegistry │   │  │
│  │  │   Extractor  │  │  (Rule-Based)│  │  (CAD Tools)  │   │  │
│  │  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘   │  │
│  │         │                 │                   │           │  │
│  │         └─────────────────┼───────────────────┘           │  │
│  │                           ↓                               │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  BridgeClient (QProcess + HTTP Client + SSE)        │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            ↕ HTTP localhost:50173
┌─────────────────────────────────────────────────────────────────┐
│              SidecarServer.py (Separate Python Process)         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              LangGraph StateGraph Engine                  │  │
│  │                                                           │  │
│  │  intake → normalize_snapshot → deterministic_validate    │  │
│  │       → llm_explain → draft_plan → approval_gate         │  │
│  │       → tool_dispatch → report_render → complete         │  │
│  │                                                           │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │         OpenAIResponder (GPT-5.4 API)               │  │  │
│  │  │         - Sends JSON snapshot (NOT images)          │  │  │
│  │  │         - Receives tool calls + explanations        │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │                                                           │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  SQLiteRunStore (runs.sqlite3)                      │  │  │
│  │  │  - Persists run state                               │  │  │
│  │  │  - LangGraph checkpointing                          │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

### FreeCAD Module (In-Process)

| Component | Responsibility |
|-----------|---------------|
| **UI/Dock Panel** | User interface, buttons, tabs, issue list, report view |
| **Snapshot Extractor** | Read FreeCAD model, extract as JSON |
| **Validators** | Run deterministic rule-based checks |
| **Tool Registry** | Execute CAD operations (create, modify, delete) |
| **Bridge Client** | Launch sidecar, HTTP requests, SSE event streaming |
| **Observers** | Watch for document/selection changes, trigger re-validation |
| **Session Objects** | Store session/report data in FreeCAD document |
| **Highlighting** | Visual highlighting of issues in 3D view |

### Sidecar Server (Separate Process)

| Component | Responsibility |
|-----------|---------------|
| **LangGraph Runtime** | State machine orchestration, checkpointing |
| **OpenAI Responder** | Call GPT API, parse responses, handle tool calls |
| **Agent Engine** | Graph nodes (intake, validate, explain, plan, etc.) |
| **Run Store** | SQLite persistence for runs and state |
| **HTTP API** | REST endpoints + Server-Sent Events |

---

## Communication Protocol

### HTTP Endpoints (Sidecar)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/v1/runs` | POST | Start new validation run |
| `/v1/runs/{run_id}/events` | GET | SSE event stream |
| `/v1/runs/{run_id}/resume` | POST | Resume after approval |
| `/v1/runs/{run_id}/tool-results` | POST | Submit tool execution results |

### Event Types (SSE)

| Event | Direction | Payload |
|-------|-----------|---------|
| `run_started` | Sidecar → UI | Status update |
| `node_status` | Sidecar → UI | Current graph node |
| `assistant_delta` | Sidecar → UI | AI explanation text |
| `issues_delta` | Sidecar → UI | New validation issues |
| `tool_request` | Sidecar → UI | AI requests CAD operation |
| `approval_required` | Sidecar → UI | Human approval needed |
| `report_ready` | Sidecar → UI | Final report available |
| `run_finished` | Sidecar → UI | Run completed |
| `run_error` | Sidecar → UI | Error occurred |

---

## Data Structures

### DocumentSnapshot

Extracted from FreeCAD model:

```json
{
  "document_id": "uuid-here",
  "document_name": "Document",
  "document_label": "My Assembly",
  "units": 0,
  "active_workbench": "PartDesign",
  "active_object_id": "Body001",
  "selection": [{"object_name": "Body001", "subelements": []}],
  "parameters": [...],
  "objects": [...],
  "dependency_edges": [...],
  "recompute_errors": [...],
  "snapshot_hash": "sha256-hash"
}
```

### ValidationIssue

```json
{
  "issue_id": "uuid-here",
  "rule_id": "null-shape",
  "severity": "high",
  "category": "geometry",
  "source": "deterministic",
  "confidence": 0.92,
  "object_ref": {"object_name": "Body001"},
  "subelement_ref": {},
  "evidence": {...},
  "message": "Object has null shape",
  "recommended_fix": "Inspect the generating feature",
  "highlight_mode": "object"
}
```

### ProposedChange

```json
{
  "change_id": "uuid-here",
  "summary": "Add 5mm fillet to Edge3",
  "risk_level": "low",
  "ops": [
    {"op": "fillet", "object_name": "Body001", "edges": ["Edge3"], "radius": 5.0},
    {"op": "recompute"}
  ]
}
```

### ValidationReport

```json
{
  "report_id": "uuid-here",
  "thread_id": "openai-thread-id",
  "snapshot_hash": "sha256-hash",
  "summary": "Reviewed 5 objects, found 3 issues",
  "issue_counts": {"total": 3, "high": 1, "medium": 2},
  "issues": [...],
  "proposed_changes": [...],
  "model_info": {...},
  "rulepack_version": "v1",
  "created_at": "2026-03-30T12:00:00Z",
  "markdown": "# Report...",
  "html": "<html>..."
}
```

---

## File Locations

### Source Code

```
src/Mod/MagicCADAI/
├── Init.py                    # Module init
├── InitGui.py                 # Workbench registration
├── Commands.py                # FreeCAD commands
├── DockPanel.py               # UI controller
├── Snapshot.py                # JSON extraction
├── Validators.py              # Rule checks
├── ToolRegistry.py            # CAD operations
├── BridgeClient.py            # Sidecar client
├── SidecarServer.py           # LangGraph server
├── SessionObjects.py          # Document storage
├── Observers.py               # Change observers
├── Highlighting.py            # Issue highlighting
├── QtCompat.py                # Qt abstraction
└── __init__.py                # Package init
```

### Runtime Data

```
~/.local/share/FreeCAD/MagicCADAI/
└── runs.sqlite3               # Run persistence
```

---

## Key Design Patterns

| Pattern | Usage |
|---------|-------|
| **Bridge Pattern** | FreeCAD module ↔ Sidecar server communication |
| **Observer Pattern** | Document and selection change notifications |
| **State Pattern** | LangGraph state machine for workflow |
| **Command Pattern** | FreeCAD commands (Validate, Apply, Export) |
| **Strategy Pattern** | Model selection (gpt-5.4, pro, mini) |
| **Memento Pattern** | Session/Report persistence in document |

---

## Dependencies

### Python Packages

| Package | Purpose |
|---------|---------|
| `openai` | OpenAI API client |
| `langgraph` | State machine orchestration |
| `langchain` | (via langgraph) |
| `PySide` / `PyQt` | Qt bindings (via QtCompat) |

### FreeCAD Workbenches Used

| Workbench | Usage |
|-----------|-------|
| `PartDesign` | Primary modeling workbench |
| `Sketcher` | Sketch-based features |
| `Part` | Boolean operations, primitives |

---

## Related Documents

- `02_data_flow.md` - Detailed data flow
- `05_ai_integration.md` - AI/LLM integration details
- `09_sidecar_server.md` - Sidecar architecture
- `/plan.md` - Original architecture plan
