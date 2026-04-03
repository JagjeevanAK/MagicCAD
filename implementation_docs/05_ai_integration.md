# AI Integration (OpenAI + Gemini + LangGraph)

## Purpose

This document describes how MagicCAD AI integrates with OpenAI's GPT models, Google's Gemini models, and uses LangGraph for workflow orchestration.

---

## Files

| File | Purpose |
|------|---------|
| `SidecarServer.py` | Main AI integration (OpenAIResponder, GeminiResponder, LangGraphRuntime, MagicCADAgentEngine) |
| `BridgeClient.py` | FreeCAD → Sidecar communication |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  FreeCAD Module                                             │
│  - Extracts snapshot                                        │
│  - Runs validators                                          │
│  - Sends to sidecar via HTTP                                │
└─────────────────────────────────────────────────────────────┘
                    ↓ HTTP localhost:50173
┌─────────────────────────────────────────────────────────────┐
│  SidecarServer.py                                           │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  OpenAIResponder                                      │  │
│  │  - Calls OpenAI Responses API                         │  │
│  │  - Handles function calling                           │  │
│  │  - Maintains conversation continuity                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  GeminiResponder                                      │  │
│  │  - Calls Google Gemini API                            │  │
│  │  - Handles function calling                           │  │
│  │  - Auto-detected based on model name                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  LangGraphRuntime                                     │  │
│  │  - Compiles StateGraph                                │  │
│  │  - Manages checkpoints (SQLite)                       │  │
│  │  - Handles interrupts (approval, tool results)        │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  MagicCADAgentEngine                                  │  │
│  │  - Graph node implementations                         │  │
│  │  - Routing logic                                      │  │
│  │  - Report generation                                  │  │
│  │  - Auto-selects OpenAI or Gemini based on model       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                    ↓ HTTPS
┌─────────────────────────────────────────────────────────────┐
│  OpenAI API                      │  Google AI API           │
│  - GPT-5.4 (primary)             │  - gemini-2.0-flash      │
│  - GPT-5.4-pro (deep review)     │  - gemini-1.5-pro        │
│  - GPT-5.4-mini (triage)         │  - gemini-1.5-flash      │
└─────────────────────────────────────────────────────────────┘
```

---

## OpenAI Configuration

### Environment Variable

```python
import os
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
```

**Must be set before using AI features.**

---

### Model Selection

```python
MODEL_OPTIONS = ("gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini")

DEFAULT_MODEL = "gpt-5.4"
```

| Model | Use Case | Cost | Speed |
|-------|----------|------|-------|
| `gpt-5.4` | Primary validation and copilot | Medium | Fast |
| `gpt-5.4-pro` | Deep review, complex reasoning | High | Slow |
| `gpt-5.4-mini` | Background triage, classification | Low | Very Fast |

---

## Gemini Configuration

### Environment Variable

```python
import os
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
```

**Must be set before using Gemini models.**

---

### Model Selection

```python
GEMINI_MODEL_OPTIONS = ("gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash")

GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"
```

| Model | Use Case | Cost | Speed |
|-------|----------|------|-------|
| `gemini-2.0-flash` | Primary validation and copilot | Low | Very Fast |
| `gemini-1.5-pro` | Deep review, complex reasoning | Medium | Fast |
| `gemini-1.5-flash` | Background triage, classification | Very Low | Ultra Fast |

---

### Automatic Provider Detection

The system automatically detects which provider to use based on the model name:

```python
def _get_model_provider(model_name):
    """Detect which provider to use based on model name."""
    if not model_name:
        return "openai"
    model_lower = model_name.lower()
    if model_lower.startswith("gemini"):
        return "gemini"
    return "openai"
```

**Examples:**
- `model="gemini-2.0-flash"` → Uses Gemini API
- `model="gpt-5.4"` → Uses OpenAI API
- `model="gpt-5.4-pro"` → Uses OpenAI API
- No model specified → Uses OpenAI API (default)

---

## Gemini Responder

### Initialization

```python
class GeminiResponder:
    def __init__(self):
        self._client = None
        self._model = None
        self._error = ""

        if not os.environ.get("GEMINI_API_KEY"):
            self._error = "GEMINI_API_KEY is not set"
            return

        try:
            import google.generativeai as genai
            genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
            self._client = genai
        except Exception as exc:
            self._error = str(exc)

    @property
    def available(self):
        return self._client is not None
```

---

### Explain Function (Main AI Call)

```python
def explain(self, state):
    if not self.available:
        return {"assistant_text": "", "assistant_phase": state.get("assistant_phase", "")}

    snapshot = state.get("snapshot", {})
    issues = state.get("issues", [])
    prompt = state.get("prompt", "")
    model_name = state.get("model", GEMINI_DEFAULT_MODEL)
    phase = state.get("assistant_phase", "") or ("copilot" if prompt else "validate")

    payload = {
        "phase": phase,
        "intent": state.get("intent", "validate"),
        "prompt": prompt,
        "issue_count": len(issues),
        "issues": issues[:10],  # Limit to top 10
        "objects": snapshot.get("objects", [])[:20],  # Limit to 20
        "selection": snapshot.get("selection", []),
        "tool_results": state.get("tool_results", [])[-3:],  # Last 3
    }

    # System prompt
    system_prompt = (
        "You are MagicCAD AI. Provide concise, actionable CAD review feedback "
        "for a FreeCAD-based desktop tool. If you need more detail, call a "
        "read-only tool. Never ask to run arbitrary Python. When you answer "
        "directly, return clear prose only."
    )

    try:
        # Get or create model instance
        if self._model is None or self._model.name != model_name:
            self._model = self._client.GenerativeModel(model_name)
        model = self._model

        # API call
        response = model.generate_content(
            contents=[
                {"role": "user", "parts": [system_prompt + "\n\nUser request: " + json.dumps(payload)]}
            ],
            tools=self._build_gemini_tools(),
            generation_config={
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 2048,
            }
        )
        return self._parse_response(response)
    except Exception as exc:
        self._error = str(exc)
        return {"assistant_text": "", "assistant_phase": phase}
```

---

### Build Gemini Tools

```python
def _build_gemini_tools(self):
    """Build Gemini-compatible tool specs from READ_ONLY_TOOL_SPECS."""
    return [
        {
            "function_declarations": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                }
                for tool in READ_ONLY_TOOL_SPECS
            ]
        }
    ]
```

**Key Points:**
- Converts OpenAI tool format to Gemini function declarations
- Same read-only tools exposed to Gemini
- Schema validation enforced

---

### Response Parsing

```python
def _parse_response(self, response):
    """Parse Gemini API response to match OpenAI response format."""
    text = ""
    tool_request = None

    try:
        # Extract text response
        if hasattr(response, "text") and response.text:
            text = response.text.strip()

        # Extract function call if present
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                for part in candidate.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        arguments = {}
                        if hasattr(fc, "args"):
                            arguments = dict(fc.args)
                        tool_request = {
                            "request_id": uuid.uuid4().hex,
                            "call_id": fc.name if hasattr(fc, "name") else "",
                            "tool_name": fc.name if hasattr(fc, "name") else "",
                            "arguments": arguments,
                        }
                        break
    except Exception:
        pass

    payload = {
        "assistant_text": text,
        "assistant_phase": "",
        "previous_response_id": "",
    }

    if tool_request:
        payload["pending_tool_request"] = tool_request
        payload["tool_return_to"] = "llm_explain"

    return payload
```

**Returns:**
```python
{
    "assistant_text": "I found 3 issues...",
    "assistant_phase": "validate",
    "previous_response_id": "gemini-2.0-flash",
    "pending_tool_request": {...}  # Optional
}
```

**Key Differences from OpenAI:**
- Gemini doesn't support `previous_response_id` for conversation continuity (as of v1)
- Response format differs but normalized to match OpenAI structure
- Function calling uses `function_call` instead of `function_call` item type

---

## OpenAI Responder

### Initialization

```python
class OpenAIResponder:
    def __init__(self):
        self._client = None
        self._error = ""
        
        if not os.environ.get("OPENAI_API_KEY"):
            self._error = "OPENAI_API_KEY is not set"
            return
        
        try:
            from openai import OpenAI
            self._client = OpenAI()
        except Exception as exc:
            self._error = str(exc)
    
    @property
    def available(self):
        return self._client is not None
```

---

### Explain Function (Main AI Call)

```python
def explain(self, state):
    if not self.available:
        return {"assistant_text": "", "assistant_phase": state.get("assistant_phase", "")}
    
    # Prepare payload for GPT
    snapshot = state.get("snapshot", {})
    issues = state.get("issues", [])
    prompt = state.get("prompt", "")
    model = state.get("model", DEFAULT_MODEL)
    phase = state.get("assistant_phase", "") or ("copilot" if prompt else "validate")
    
    payload = {
        "phase": phase,
        "intent": state.get("intent", "validate"),
        "prompt": prompt,
        "issue_count": len(issues),
        "issues": issues[:10],  # Limit to top 10
        "objects": snapshot.get("objects", [])[:20],  # Limit to 20
        "selection": snapshot.get("selection", []),
        "tool_results": state.get("tool_results", [])[-3:],  # Last 3
    }
    
    # System prompt
    system_prompt = (
        "You are MagicCAD AI. Provide concise, actionable CAD review feedback "
        "for a FreeCAD-based desktop tool. If you need more detail, call a "
        "read-only tool. Never ask to run arbitrary Python. When you answer "
        "directly, return clear prose only."
    )
    
    # API call
    kwargs = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload)}]},
        ],
        "tools": READ_ONLY_TOOL_SPECS,
    }
    
    # Maintain conversation continuity
    previous_response_id = state.get("previous_response_id", "")
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    
    try:
        response = self._client.responses.create(**kwargs)
        return self._parse_response(response)
    except Exception as exc:
        self._error = str(exc)
        return {"assistant_text": "", "assistant_phase": phase}
```

---

### Read-Only Tool Specs

```python
READ_ONLY_TOOL_SPECS = [
    {
        "type": "function",
        "name": "get_document_snapshot",
        "description": "Request a fresh read-only document snapshot from the desktop module.",
        "parameters": {
            "type": "object",
            "properties": {
                "selection_only": {
                    "type": "boolean",
                    "description": "When true, only request the current selection neighborhood.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_object_details",
        "description": "Request read-only details for a specific object already present in the snapshot.",
        "parameters": {
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "The internal FreeCAD object name.",
                }
            },
            "required": ["object_name"],
            "additionalProperties": False,
        },
    },
]
```

**Key Points:**
- Only read-only tools exposed to AI
- Mutating operations (apply_ops) handled separately via approval flow
- Schema validation enforced

---

### Response Parsing

```python
def _parse_response(self, response):
    text = getattr(response, "output_text", "") or ""
    tool_request = None
    
    for item in getattr(response, "output", []) or []:
        item_type = _field(item, "type")
        
        # Check for function call
        if item_type == "function_call":
            arguments = _safe_json_loads(_field(item, "arguments", "{}"), {})
            tool_request = {
                "request_id": uuid.uuid4().hex,
                "call_id": _field(item, "call_id", ""),
                "tool_name": _field(item, "name", ""),
                "arguments": arguments,
            }
            break
        
        # Extract text output
        if item_type == "message":
            for content in _field(item, "content", []) or []:
                if _field(content, "type") == "output_text":
                    text = text or _field(content, "text", "")
    
    payload = {
        "assistant_text": (text or "").strip(),
        "assistant_phase": "",
        "previous_response_id": _field(response, "id", ""),
    }
    
    if tool_request:
        payload["pending_tool_request"] = tool_request
        payload["tool_return_to"] = "llm_explain"
    
    return payload
```

**Returns:**
```python
{
    "assistant_text": "I found 3 issues...",
    "assistant_phase": "validate",
    "previous_response_id": "resp_abc123",
    "pending_tool_request": {...}  # Optional
}
```

---

## LangGraph Integration

### Graph Structure

```python
from langgraph.graph import END, START, StateGraph

graph = StateGraph(dict)

# Add nodes
graph.add_node("intake", self._wrap("intake", engine.intake))
graph.add_node("normalize_snapshot", self._wrap("normalize_snapshot", engine.normalize_snapshot))
graph.add_node("deterministic_validate", self._wrap("deterministic_validate", engine.deterministic_validate))
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
```

---

### Checkpointing (Persistence)

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string(database_path)
# or
checkpointer = SqliteSaver(sqlite3.connect(database_path, check_same_thread=False))

compiled_graph = graph.compile(checkpointer=checkpointer)
```

**Database:** `~/.local/share/FreeCAD/MagicCADAI/runs.sqlite3`

**Purpose:**
- Resume interrupted runs
- Maintain conversation history
- Debug/replay runs

---

### Interrupts (Human-in-the-Loop)

```python
from langgraph.types import interrupt

def approval_gate(self, state):
    proposed_changes = state.get("proposed_changes", [])
    if not proposed_changes:
        return {"approval_status": "not_required"}
    
    # Create interrupt payload
    request = {
        "interrupt_kind": "approval",
        "message": "Approval is required before MagicCAD AI applies local document changes.",
        "proposed_changes": proposed_changes,
    }
    
    # Trigger interrupt (pauses graph execution)
    decision_payload = self._langgraph.interrupt(request)
    
    # Process decision
    decision = _field(decision_payload, "decision")  # "approve", "edit", or "reject"
    # ...
```

**Interrupt Types:**
1. `approval` - Wait for human approval decision
2. `tool` - Wait for tool execution results

---

### Graph Invocation

```python
def _drive_graph(self, run, mode="start", resume_payload=None):
    self._local.run = run
    config = {"configurable": {"thread_id": run.thread_id}}
    
    if mode == "start":
        # Initial invocation
        result = self._langgraph.initial_invoke(dict(run.state), config)
    else:
        # Resume after interrupt
        result = self._langgraph.resume_invoke(resume_payload, config)
    
    # Update state from graph result
    graph_state = self._langgraph.current_state(config, result)
    run.state.update(graph_state)
    self._persist(run)
```

---

## Graph Node Implementations

### intake

```python
def intake(self, state):
    summary = "Intake complete for {0} objects.".format(
        len(state.get("snapshot", {}).get("objects", []))
    )
    return {"assistant_phase": "intake", "summary": summary}
```

---

### normalize_snapshot

```python
def normalize_snapshot(self, state):
    snapshot = dict(state.get("snapshot", {}) or {})
    snapshot.setdefault("objects", [])
    snapshot.setdefault("selection", [])
    snapshot.setdefault("dependency_edges", [])
    snapshot.setdefault("recompute_errors", [])
    return {"assistant_phase": "normalize_snapshot", "snapshot": snapshot}
```

---

### deterministic_validate

```python
def deterministic_validate(self, state):
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

---

### llm_explain

```python
def llm_explain(self, state):
    # Auto-select responder based on model
    responder, provider = self._get_responder(state)
    explanation = responder.explain(state)
    text = explanation.get("assistant_text", "")

    # Fallback if AI fails
    if not text:
        text = self._fallback_explanation(
            state.get("snapshot", {}),
            state.get("issues", []),
            state.get("prompt", "")
        )

    return {
        "assistant_phase": explanation.get("assistant_phase", "llm_explain"),
        "assistant_text": text,
        "previous_response_id": explanation.get("previous_response_id", ""),
        "pending_tool_request": explanation.get("pending_tool_request"),
        "tool_return_to": explanation.get("tool_return_to", ""),
        "backend": {
            "openai": self._openai_responder.available,
            "gemini": self._gemini_responder.available,
            "langgraph": self._langgraph.available,
            "model": state.get("model", DEFAULT_MODEL),
            "provider": provider,  # "openai" or "gemini"
        },
    }
```

**Key Changes:**
- Auto-detects provider based on model name
- Reports both OpenAI and Gemini availability
- Includes `provider` field in backend info

---

### draft_plan

```python
def draft_plan(self, state):
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

---

### approval_gate

See `07_approval_system.md` for details.

---

### tool_dispatch

```python
def tool_dispatch(self, state):
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
    
    # Request tool execution
    request = dict(tool_request)
    request.setdefault("interrupt_kind", "tool")
    self._publish(run, "tool_request", **request)
    
    # Wait for tool result (interrupt)
    tool_result = self._langgraph.interrupt(request)
    
    # Collect results
    collected = list(state.get("tool_results", []))
    collected.append(tool_result or {"result": {"ok": False, "error": "No tool result received"}})
    
    return {
        "pending_tool_request": None,
        "tool_results": collected,
    }
```

---

### report_render

```python
def report_render(self, state):
    return {
        "assistant_phase": "report_render",
        "report": self._render_report(state),
    }
```

---

### complete

```python
def complete(self, state):
    return {"assistant_phase": "complete"}
```

---

## Routing Logic

### After llm_explain

```python
def route_after_llm_explain(self, state):
    return "tool_dispatch" if state.get("pending_tool_request") else "draft_plan"
```

---

### After draft_plan

```python
def route_after_draft_plan(self, state):
    if state.get("pending_tool_request"):
        return "tool_dispatch"
    if state.get("proposed_changes"):
        return "approval_gate"
    return "report_render"
```

---

### After approval_gate

```python
def route_after_approval_gate(self, state):
    if state.get("approval_status") == "edited":
        return "draft_plan"  # Revise and re-approve
    if state.get("pending_tool_request"):
        return "tool_dispatch"
    return "report_render"
```

---

### After tool_dispatch

```python
def route_after_tool_dispatch(self, state):
    return state.get("tool_return_to", "") or "report_render"
```

---

## Fallback Explanation

When AI is unavailable:

```python
def _fallback_explanation(self, snapshot, issues, prompt):
    object_count = len(snapshot.get("objects", []))
    counts = Validators.issue_counts(issues)
    
    summary = "Reviewed {0} objects and found {1} issues.".format(
        object_count, counts.get("total", 0)
    )
    
    if prompt:
        summary += " Request: {0}".format(prompt.strip())
    
    if issues:
        summary += " Highest priority: {0}".format(issues[0].get("message", ""))
    else:
        summary += " No deterministic validation risks were detected."
    
    return summary
```

---

## Error Handling

```python
try:
    response = self._client.responses.create(**kwargs)
except Exception as exc:
    self._error = str(exc)
    return {"assistant_text": "", "assistant_phase": phase}
```

**Graceful Degradation:**
- Missing API key → Show error, use fallback
- Network error → Retry, then fallback
- Rate limit → Queue, retry later
- Model error → Use fallback explanation

---

## Related Documents

- `02_data_flow.md` - Data flow through AI system
- `07_approval_system.md` - Approval gate details
- `11_langgraph_workflow.md` - Detailed LangGraph workflow
