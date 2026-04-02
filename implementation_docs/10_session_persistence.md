# Session Persistence

## Purpose

Session Persistence stores validation session data and reports directly in the FreeCAD document. This allows sessions to survive document save/reopen and provides audit trails.

---

## File Location

```
src/Mod/MagicCADAI/SessionObjects.py
```

---

## Architecture

```
FreeCAD Document
└── MagicCADAIData (Group)
    ├── MagicCADAISession (FeaturePython)
    │   └── Stores: thread_id, run_id, model, status, etc.
    └── MagicCADAIReport (FeaturePython)
        └── Stores: report_id, issues, markdown, html, etc.
```

---

## Storage Objects

### Root Group: MagicCADAIData

```python
class RootProxy(_BaseProxy):
    proxy_type = "MagicCADAI::Root"
    
    def ensure_properties(self, obj):
        _ensure_property(
            obj, 
            "App::PropertyString", 
            "Kind", 
            "MagicCADAI", 
            "Storage type", 
            "Root"
        )
```

**Purpose:** Groups all MagicCAD AI objects together in the document tree.

---

### Session Object: MagicCADAISession

```python
class SessionProxy(_BaseProxy):
    proxy_type = "MagicCADAI::Session"
    
    def ensure_properties(self, obj):
        _ensure_property(obj, "App::PropertyString", "Kind", "MagicCADAI", 
                        "Storage type", "Session")
        
        # Session metadata
        _ensure_property(obj, "App::PropertyString", "ThreadId", "MagicCADAI", 
                        "LangGraph/OpenAI thread id", "")
        _ensure_property(obj, "App::PropertyString", "LastRunId", "MagicCADAI", 
                        "Last sidecar run id", "")
        _ensure_property(obj, "App::PropertyString", "ModelName", "MagicCADAI", 
                        "Selected model", "")
        _ensure_property(obj, "App::PropertyString", "LastStatus", "MagicCADAI", 
                        "Last run status", "")
        _ensure_property(obj, "App::PropertyString", "LastSnapshotHash", 
                        "MagicCADAI", "Last snapshot hash", "")
        _ensure_property(obj, "App::PropertyString", "PreviousResponseId", 
                        "MagicCADAI", "Last OpenAI response id", "")
        _ensure_property(obj, "App::PropertyString", "LastPhase", "MagicCADAI", 
                        "Last assistant phase", "")
        _ensure_property(obj, "App::PropertyString", "LastUpdatedUtc", 
                        "MagicCADAI", "Last update time", "")
        
        # Serialized payload for complex data
        _ensure_property(obj, "App::PropertyString", "Payload", "MagicCADAI", 
                        "Serialized session data", "{}")
```

**Stored Properties:**

| Property | Type | Purpose |
|----------|------|---------|
| `Kind` | String | Type identifier |
| `ThreadId` | String | OpenAI conversation thread ID |
| `LastRunId` | String | Last sidecar run ID |
| `ModelName` | String | GPT model used (e.g., "gpt-5.4") |
| `LastStatus` | String | Last run status |
| `LastSnapshotHash` | String | Hash of last validated snapshot |
| `PreviousResponseId` | String | For conversation continuity |
| `LastPhase` | String | Last AI phase (validate, copilot, etc.) |
| `LastUpdatedUtc` | String | ISO timestamp |
| `Payload` | JSON string | Additional session data |

---

### Report Object: MagicCADAIReport

```python
class ReportProxy(_BaseProxy):
    proxy_type = "MagicCADAI::ValidationReport"
    
    def ensure_properties(self, obj):
        _ensure_property(obj, "App::PropertyString", "Kind", "MagicCADAI", 
                        "Storage type", "Report")
        
        # Report metadata
        _ensure_property(obj, "App::PropertyString", "ReportId", "MagicCADAI", 
                        "Current report id", "")
        _ensure_property(obj, "App::PropertyString", "ThreadId", "MagicCADAI", 
                        "Conversation thread id", "")
        _ensure_property(obj, "App::PropertyString", "SnapshotHash", "MagicCADAI", 
                        "Snapshot hash", "")
        _ensure_property(obj, "App::PropertyString", "Summary", "MagicCADAI", 
                        "Report summary", "")
        
        # Issue counts
        _ensure_property(obj, "App::PropertyInteger", "IssueCount", "MagicCADAI", 
                        "Number of issues", 0)
        
        # Report content
        _ensure_property(obj, "App::PropertyString", "Markdown", "MagicCADAI", 
                        "Markdown report body", "")
        _ensure_property(obj, "App::PropertyString", "Html", "MagicCADAI", 
                        "HTML report body", "")
        
        # Full serialized report
        _ensure_property(obj, "App::PropertyString", "Payload", "MagicCADAI", 
                        "Serialized report payload", "{}")
```

**Stored Properties:**

| Property | Type | Purpose |
|----------|------|---------|
| `Kind` | String | Type identifier |
| `ReportId` | String | Unique report ID |
| `ThreadId` | String | Associated conversation thread |
| `SnapshotHash` | String | Hash of validated snapshot |
| `Summary` | String | Brief summary |
| `IssueCount` | Integer | Total issues found |
| `Markdown` | String | Markdown report |
| `Html` | String | HTML report |
| `Payload` | JSON string | Full report JSON |

---

## Core Functions

### ensure_storage

```python
def ensure_storage(document=None):
    """
    Ensure MagicCAD AI storage objects exist in document.
    
    Args:
        document: FreeCAD document (default: ActiveDocument)
    
    Returns:
        Tuple of (root, session, report) objects
    """
    document = document or FreeCAD.ActiveDocument
    if document is None:
        return None, None, None
    
    # Create/get root group
    root = _ensure_root(document)
    
    # Create/get session object
    session = _ensure_feature(document, SESSION_NAME, SessionProxy)
    
    # Create/get report object
    report = _ensure_feature(document, REPORT_NAME, ReportProxy)
    
    # Add to root group if not already
    current = set(obj.Name for obj in root.Group)
    wanted = [session, report]
    for obj in wanted:
        if obj.Name not in current:
            root.addObject(obj)
    
    return root, session, report
```

---

### update_session

```python
def update_session(
    session,
    thread_id=None,
    run_id=None,
    model=None,
    status=None,
    snapshot_hash=None,
    previous_response_id=None,
    last_phase=None,
    payload=None,
):
    """
    Update session object with new values.
    
    Args:
        session: Session object
        thread_id: OpenAI thread ID
        run_id: Sidecar run ID
        model: Model name
        status: Run status
        snapshot_hash: Snapshot hash
        previous_response_id: OpenAI response ID
        last_phase: AI phase
        payload: Additional data dict
    """
    if session is None:
        return
    
    if thread_id is not None:
        session.ThreadId = thread_id
    if run_id is not None:
        session.LastRunId = run_id
    if model is not None:
        session.ModelName = model
    if status is not None:
        session.LastStatus = status
    if snapshot_hash is not None:
        session.LastSnapshotHash = snapshot_hash
    if previous_response_id is not None:
        session.PreviousResponseId = previous_response_id
    if last_phase is not None:
        session.LastPhase = last_phase
    
    session.LastUpdatedUtc = _utc_now()
    
    if payload is not None:
        session.Payload = json.dumps(payload, sort_keys=True)
```

**Usage:**
```python
root, session, report = SessionObjects.ensure_storage()
SessionObjects.update_session(
    session,
    thread_id="thread-abc123",
    run_id="run-xyz789",
    model="gpt-5.4",
    snapshot_hash="sha256-...",
)
```

---

### update_report

```python
def update_report(report, report_data):
    """
    Update report object with validation report data.
    
    Args:
        report: Report object
        report_data: ValidationReport dict from sidecar
    """
    if report is None or not report_data:
        return
    
    report.ReportId = report_data.get("report_id", "")
    report.ThreadId = report_data.get("thread_id", "")
    report.SnapshotHash = report_data.get("snapshot_hash", "")
    report.Summary = report_data.get("summary", "")
    report.IssueCount = int(
        report_data.get("issue_counts", {}).get(
            "total", len(report_data.get("issues", []))
        )
    )
    report.Markdown = report_data.get("markdown", "")
    report.Html = report_data.get("html", "")
    report.Payload = json.dumps(report_data, sort_keys=True)
```

**Usage:**
```python
report_data = {
    "report_id": "report-001",
    "thread_id": "thread-abc",
    "snapshot_hash": "sha256-...",
    "summary": "Found 3 issues",
    "issue_counts": {"total": 3, "high": 1, "medium": 2},
    "issues": [...],
    "markdown": "# Report...",
    "html": "<html>...",
}
SessionObjects.update_report(report, report_data)
```

---

### Payload Accessors

```python
def session_payload(session):
    """Get deserialized session payload."""
    try:
        return json.loads(session.Payload) if session and session.Payload else {}
    except Exception:
        return {}

def report_payload(report):
    """Get deserialized report payload."""
    try:
        return json.loads(report.Payload) if report and report.Payload else {}
    except Exception:
        return {}
```

---

## Helper Functions

### _ensure_root

```python
def _ensure_root(document):
    """Create or get MagicCADAIData root group."""
    root = document.getObject(ROOT_NAME)  # "MagicCADAIData"
    
    if root is None:
        root = document.addObject("App::DocumentObjectGroupPython", ROOT_NAME)
        RootProxy(root)
        _ensure_view_provider(root)
    elif getattr(getattr(root, "Proxy", None), "Type", "") != RootProxy.proxy_type:
        RootProxy(root)
        _ensure_view_provider(root)
    
    return root
```

---

### _ensure_feature

```python
def _ensure_feature(document, name, proxy_class):
    """Create or get FeaturePython object with specified proxy."""
    obj = document.getObject(name)
    
    if obj is None:
        obj = document.addObject("App::FeaturePython", name)
        proxy_class(obj)
        _ensure_view_provider(obj)
    elif getattr(getattr(obj, "Proxy", None), "Type", "") != proxy_class.proxy_type:
        proxy_class(obj)
        _ensure_view_provider(obj)
    else:
        obj.Proxy.ensure_properties(obj)
    
    return obj
```

---

### _ensure_property

```python
def _ensure_property(obj, type_name, name, group, doc, default=None):
    """Add property to object if it doesn't exist."""
    if name not in obj.PropertiesList:
        obj.addProperty(type_name, name, group, doc, locked=True)
        if default is not None:
            try:
                setattr(obj, name, default)
            except Exception:
                pass
```

**Usage:**
```python
_ensure_property(
    obj,
    "App::PropertyString",      # Property type
    "ThreadId",                 # Property name
    "MagicCADAI",               # Group in property editor
    "LangGraph thread id",      # Tooltip
    ""                          # Default value
)
```

---

### _ensure_view_provider

```python
def _ensure_view_provider(obj):
    """Ensure object has a view provider (GUI icon)."""
    if not FreeCAD.GuiUp:
        return
    
    try:
        if getattr(obj.ViewObject, "Proxy", None) is None:
            _ViewProvider(obj.ViewObject)
    except Exception:
        pass
```

---

### _ViewProvider

```python
class _ViewProvider:
    """Generic view provider for MagicCAD AI objects."""
    
    def __init__(self, vobj):
        vobj.Proxy = self
    
    def attach(self, vobj):
        self.ViewObject = vobj
    
    def getIcon(self):
        return ":/icons/help-browser.svg"
    
    def dumps(self):
        return None
    
    def loads(self, state):
        return None
```

---

### _utc_now

```python
def _utc_now():
    """Get current UTC timestamp in ISO format."""
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
```

---

## Constants

```python
ROOT_NAME = "MagicCADAIData"
SESSION_NAME = "MagicCADAISession"
REPORT_NAME = "MagicCADAIReport"
```

---

## Base Proxy Classes

### _BaseProxy

```python
class _BaseProxy:
    proxy_type = "MagicCADAI::Base"
    
    def __init__(self, obj):
        self.Type = self.proxy_type
        self.ensure_properties(obj)
        obj.Proxy = self
    
    def ensure_properties(self, obj):
        pass
    
    def onDocumentRestored(self, obj):
        self.ensure_properties(obj)
    
    def dumps(self):
        return None
    
    def loads(self, state):
        return None
```

**Purpose:** Base class for all proxy types. Provides standard interface.

---

## Document Restoration

When a FreeCAD document is opened, proxies are restored automatically:

```python
def onDocumentRestored(self, obj):
    """Called when document is loaded."""
    self.ensure_properties(obj)
```

This ensures properties exist even if the code version changed.

---

## Usage Examples

### Start New Validation Session

```python
# Get storage objects
root, session, report = SessionObjects.ensure_storage()

# Update session with run info
SessionObjects.update_session(
    session,
    thread_id="thread-abc123",
    run_id="run-xyz789",
    model="gpt-5.4",
    status="running",
)

# ... run validation ...

# Update with results
SessionObjects.update_session(
    session,
    status="completed",
    previous_response_id="resp-001",
)
```

---

### Save Validation Report

```python
# Get storage objects
root, session, report = SessionObjects.ensure_storage()

# Report data from sidecar
report_data = {
    "report_id": "report-001",
    "thread_id": "thread-abc123",
    "snapshot_hash": "sha256-...",
    "summary": "Found 3 issues",
    "issue_counts": {"total": 3, "high": 1, "medium": 2},
    "issues": [...],
    "proposed_changes": [...],
    "markdown": "# MagicCAD AI Validation Report\n\n...",
    "html": "<html><body>...</body></html>",
}

# Save to document
SessionObjects.update_report(report, report_data)
```

---

### Restore Previous Session

```python
# Get storage objects
root, session, report = SessionObjects.ensure_storage()

# Read session data
session_data = SessionObjects.session_payload(session)
thread_id = session.ThreadId
last_run_id = session.LastRunId
model = session.ModelName

# Read report data
report_data = SessionObjects.report_payload(report)
issues = report_data.get("issues", [])
markdown = report_obj.Markdown
```

---

## Benefits

| Benefit | Description |
|---------|-------------|
| **Persistence** | Data survives document save/reopen |
| **Audit Trail** | Full history of validations |
| **Portability** | Report travels with document |
| **Continuity** | Resume conversations across sessions |
| **Integration** | Native FreeCAD objects |

---

## Related Documents

- `02_data_flow.md` - Session in data flow
- `08_ui_components.md` - UI usage of session objects
- `09_sidecar_server.md` - Report generation
