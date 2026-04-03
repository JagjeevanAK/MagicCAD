# Sidecar Server

## Purpose

The Sidecar Server is a separate Python process that runs the LangGraph state machine and OpenAI API integration. It communicates with the FreeCAD module via HTTP.

---

## File Location

```
src/Mod/MagicCADAI/SidecarServer.py
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  SidecarServer.py (Standalone Python Process)               │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  ThreadingHTTPServer (localhost:50173)                │  │
│  │  - /health                                            │  │
│  │  - /v1/runs (POST)                                    │  │
│  │  - /v1/runs/{id}/events (SSE)                         │  │
│  │  - /v1/runs/{id}/resume (POST)                        │  │
│  │  - /v1/runs/{id}/tool-results (POST)                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  ServerState                                          │  │
│  │  - SQLiteRunStore (persistence)                       │  │
│  │  - MagicCADAgentEngine (AI logic)                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  LangGraphRuntime                                     │  │
│  │  - StateGraph compilation                             │  │
│  │  - Checkpoint management                              │  │
│  │  - Interrupt handling                                 │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  OpenAIResponder                                      │  │
│  │  - GPT API calls                                      │  │
│  │  - Function calling                                   │  │
│  │  - Response parsing                                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## HTTP Server

### Server Initialization

```python
def main(argv=None):
    args = parse_args(argv)
    
    # Create server
    server = ThreadingHTTPServer(
        (args.host, args.port), 
        RequestHandler
    )
    server.state = ServerState(args.database)
    
    print("MagicCADAI sidecar listening on http://{0}:{1}".format(
        args.host, args.port
    ), flush=True)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
```

---

### Command Line Arguments

```python
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="MagicCAD AI sidecar server"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50173)
    parser.add_argument(
        "--database", 
        default=os.path.join(os.getcwd(), "magiccadai.sqlite3")
    )
    return parser.parse_args(argv)
```

**Defaults:**
- Host: `127.0.0.1` (localhost only)
- Port: `50173`
- Database: `./magiccadai.sqlite3`

---

## HTTP Endpoints

### GET /health

```python
def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/health":
        self._send_json(200, self.server.state.health())
        return
```

**Response:**
```json
{
  "ok": true,
  "status": "ready",
  "timestamp": "2026-03-30T12:00:00Z",
  "langgraph_enabled": true
}
```

---

### POST /v1/runs

```python
def do_POST(self):
    parsed = urlparse(self.path)
    parts = [part for part in parsed.path.split("/") if part]
    
    if parsed.path == "/v1/runs":
        request = self._read_json_body()
        run = self.server.state.create_run(request)
        self._send_json(200, {
            "ok": true,
            "run_id": run.run_id,
            "thread_id": run.thread_id
        })
        return
```

**Request:**
```json
{
  "model": "gpt-5.4",
  "intent": "validate",
  "prompt": "Check for design issues",
  "snapshot": {...},
  "selection_only": false
}
```

**Response:**
```json
{
  "ok": true,
  "run_id": "abc123",
  "thread_id": "thread-xyz789"
}
```

---

### GET /v1/runs/{run_id}/events

```python
def do_GET(self):
    parts = [part for part in parsed.path.split("/") if part]
    if (len(parts) == 4 and parts[0] == "v1" and 
        parts[1] == "runs" and parts[3] == "events"):
        
        run = self.server.state.get_run(parts[2])
        if run is None:
            self._send_json(404, {"ok": false, "error": "Run not found"})
            return
        
        self._stream_events(run)
        return
```

**Response:** Server-Sent Events (SSE)

```
event: run_started
data: {"run_id": "abc123", "status": "running"}

event: node_status
data: {"node": "intake", "status": "running"}

event: node_status
data: {"node": "intake", "status": "completed"}

event: assistant_delta
data: {"text": "I found 3 issues...", "phase": "validate"}

event: report_ready
data: {"report": {...}}

event: run_finished
data: {"status": "completed"}
```

---

### POST /v1/runs/{run_id}/resume

```python
def do_POST(self):
    parts = [part for part in parsed.path.split("/") if part]
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
            self._send_json(404, {"ok": false, "error": "Run not found"})
            return
        
        self._send_json(200, response)
        return
```

**Request:**
```json
{
  "decision": "approve",
  "payload": {
    "change_id": "change-001"
  }
}
```

**Response:**
```json
{
  "ok": true,
  "run_id": "abc123",
  "status": "running"
}
```

---

### POST /v1/runs/{run_id}/tool-results

```python
def do_POST(self):
    parts = [part for part in parsed.path.split("/") if part]
    if (len(parts) == 4 and parts[0] == "v1" and 
        parts[1] == "runs" and parts[3] == "tool-results"):
        
        body = self._read_json_body()
        try:
            response = self.server.state.submit_tool_results(
                parts[2], 
                body
            )
        except KeyError:
            self._send_json(404, {"ok": false, "error": "Run not found"})
            return
        
        self._send_json(200, response)
        return
```

**Request:**
```json
{
  "tool_result": {
    "ok": true,
    "created": ["Body001"]
  },
  "return_to": "report_render"
}
```

---

## ServerState

### Initialization

```python
class ServerState:
    def __init__(self, database_path):
        self._store = SQLiteRunStore(database_path)
        self._engine = MagicCADAgentEngine(self._store)
        self._runs = {}  # In-memory cache
        self._lock = threading.Lock()
```

---

### Health Check

```python
def health(self):
    return {
        "ok": true,
        "status": "ready",
        "timestamp": utc_now(),
        "langgraph_enabled": self._engine.langgraph_available,
    }
```

---

### Create Run

```python
def create_run(self, request):
    run = RunRecord(request)
    
    with self._lock:
        self._runs[run.run_id] = run
    
    self._store.save_run(run)
    
    # Start graph execution in background thread
    worker = threading.Thread(
        target=self._engine.start_run, 
        args=(run,), 
        daemon=True
    )
    worker.start()
    
    return run
```

---

### Get Run

```python
def get_run(self, run_id):
    # Check in-memory cache first
    with self._lock:
        run = self._runs.get(run_id)
    
    if run is not None:
        return run
    
    # Load from database
    restored = self._store.load_run(run_id)
    if restored is None:
        return None
    
    # Add to cache
    with self._lock:
        self._runs[run_id] = restored
    
    return restored
```

---

### Resume Run

```python
def resume_run(self, run_id, decision, payload):
    run = self.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    
    # Resume in background thread
    worker = threading.Thread(
        target=self._engine.resume_approval, 
        args=(run, decision, payload or {}), 
        daemon=True
    )
    worker.start()
    
    return {
        "ok": true,
        "run_id": run_id,
        "status": run.status
    }
```

---

### Submit Tool Results

```python
def submit_tool_results(self, run_id, payload):
    run = self.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    
    worker = threading.Thread(
        target=self._engine.resume_tool, 
        args=(run, payload or {}), 
        daemon=True
    )
    worker.start()
    
    return {
        "ok": true,
        "run_id": run_id
    }
```

---

## SSE Event Streaming

```python
def _stream_events(self, run):
    """Stream events to client via Server-Sent Events."""
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.end_headers()
    
    index = 0
    try:
        while True:
            with run.condition:
                # Wait for new events or terminal state
                if index >= len(run.events) and not run.terminal:
                    run.condition.wait(timeout=1.0)
                
                if index < len(run.events):
                    event = run.events[index]
                    index += 1
                elif run.terminal:
                    break
                else:
                    event = None
            
            if event is None:
                # Send ping to keep connection alive
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                continue
            
            # Send event
            payload = json.dumps(event, sort_keys=True)
            self.wfile.write(
                "event: {0}\n".format(event.get("event", "message")).encode()
            )
            self.wfile.write("data: {0}\n\n".format(payload).encode())
            self.wfile.flush()
    
    except (BrokenPipeError, ConnectionResetError):
        # Client disconnected
        return
```

---

## RunRecord

### Structure

```python
class RunRecord:
    def __init__(self, request, run_id=None, thread_id=None, 
                 status="queued", state=None, created_at=None, updated_at=None):
        self.run_id = run_id or uuid.uuid4().hex
        self.thread_id = thread_id or request.get("thread_id") or uuid.uuid4().hex
        self.status = status
        self.created_at = created_at or utc_now()
        self.updated_at = updated_at or self.created_at
        self.request = dict(request or {})
        self.state = state or self._build_initial_state(self.request)
        self.events = []
        self.condition = threading.Condition()
        self.terminal = self.status in ("completed", "error")
        self.approval_event = threading.Event()
        self.tool_result_event = threading.Event()
        self.pending_decision = None
        self.pending_decision_payload = {}
        self.pending_tool_result = None
```

---

### Initial State

```python
def _build_initial_state(self, request):
    return {
        "run_id": self.run_id,
        "thread_id": self.thread_id,
        "model": request.get("model", DEFAULT_MODEL),
        "intent": request.get("intent", "validate"),
        "prompt": request.get("prompt", ""),
        "selection_only": bool(request.get("selection_only", False)),
        "snapshot": request.get("snapshot", {}),
        "issues": [],
        "issue_counts": {"total": 0},
        "assistant_text": "",
        "assistant_phase": "",
        "previous_response_id": request.get("previous_response_id", ""),
        "proposed_changes": [],
        "approval_status": "not_required",
        "approval_feedback": "",
        "pending_tool_request": None,
        "tool_return_to": "",
        "tool_results": [],
        "report": {},
        "error": "",
    }
```

---

### Publish Event

```python
def publish(self, event_name, **payload):
    """Publish an event to the SSE stream."""
    event = {
        "event": event_name,
        "run_id": self.run_id,
        "thread_id": self.thread_id,
    }
    event.update(payload)
    
    with self.condition:
        self.events.append(event)
        self.updated_at = utc_now()
        self.condition.notify_all()  # Wake up waiting threads
    
    return event
```

---

### Close Run

```python
def close(self, status):
    """Mark run as terminal."""
    with self.condition:
        self.status = status
        self.updated_at = utc_now()
        self.terminal = True
        self.condition.notify_all()
```

---

## SQLite Persistence

### Database Schema

```python
self._db.execute("""
    create table if not exists runs (
        run_id text primary key,
        thread_id text not null,
        status text not null,
        request_json text not null default '{}',
        state_json text not null,
        report_json text,
        created_at text not null,
        updated_at text not null
    )
""")
```

---

### Save Run

```python
def save_run(self, run):
    with self._lock:
        self._db.execute("""
            insert into runs(run_id, thread_id, status, request_json, 
                            state_json, report_json, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(run_id) do update set
                thread_id=excluded.thread_id,
                status=excluded.status,
                request_json=excluded.request_json,
                state_json=excluded.state_json,
                report_json=excluded.report_json,
                updated_at=excluded.updated_at
        """, (
            run.run_id,
            run.thread_id,
            run.status,
            _json_dumps(run.request),
            _json_dumps(run.state),
            _json_dumps(run.state.get("report", {})),
            run.created_at,
            run.updated_at,
        ))
        self._db.commit()
```

---

### Load Run

```python
def load_run(self, run_id):
    with self._lock:
        row = self._db.execute("""
            select run_id, thread_id, status, request_json, state_json, 
                   created_at, updated_at
            from runs where run_id = ?
        """, (run_id,)).fetchone()
    
    if row is None:
        return None
    
    request = _safe_json_loads(row[3], {})
    state = _safe_json_loads(row[4], {})
    
    return RunRecord(
        request=request,
        run_id=row[0],
        thread_id=row[1],
        status=row[2],
        state=state,
        created_at=row[5],
        updated_at=row[6],
    )
```

---

## Helper Functions

### UTC Timestamp

```python
def utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
```

---

### JSON Helpers

```python
def _json_dumps(value):
    return json.dumps(value, sort_keys=True)

def _safe_json_loads(text, default):
    try:
        if isinstance(text, (dict, list)):
            return text
        if text is None:
            return default
        return json.loads(text)
    except Exception:
        return default
```

---

### Field Accessor

```python
def _field(obj, key, default=None):
    """Safely get field from dict or object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
```

---

## Request Handler

### JSON Response

```python
def _send_json(self, status, payload):
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)
```

---

### Read JSON Body

```python
def _read_json_body(self):
    length = int(self.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    
    body = self.rfile.read(length).decode("utf-8", "replace").strip()
    if not body.strip():
        return {}
    
    return json.loads(body)
```

---

### Logging Suppression

```python
def log_message(self, format_string, *args):
    """Suppress default HTTP logging."""
    return
```

---

## Error Handling

### Graceful Degradation

```python
def llm_explain(self, state):
    explanation = self._llm.explain(state)
    text = explanation.get("assistant_text", "")
    
    # Fallback if AI fails
    if not text:
        text = self._fallback_explanation(
            state.get("snapshot", {}),
            state.get("issues", []),
            state.get("prompt", "")
        )
    
    return {...}
```

---

### Run Error Handling

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

## Related Documents

- `01_architecture_overview.md` - Overall architecture
- `05_ai_integration.md` - AI integration details
- `11_langgraph_workflow.md` - LangGraph workflow
- `02_data_flow.md` - Data flow through sidecar
