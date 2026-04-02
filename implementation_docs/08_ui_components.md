# UI Components (Dock Panel)

## Purpose

The Dock Panel provides the user interface for MagicCAD AI within FreeCAD. It includes three tabs: Copilot, Issues, and Report.

---

## File Location

```
src/Mod/MagicCADAI/DockPanel.py
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  MagicCADAIWidget (QMainWindow)                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Control Row                                          │  │
│  │  [Model Dropdown] [Real-time Checkbox] [Status]       │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  TabWidget                                            │  │
│  │  ┌─────────┬─────────┬─────────┐                      │  │
│  │  │Copilot  │ Issues  │ Report  │                      │  │
│  │  └─────────┴─────────┴─────────┘                      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Main Components

### MagicCADAIWidget

The main UI widget containing all panels.

```python
class MagicCADAIWidget(QtWidgets.QWidget):
    def __init__(self, controller, parent=None):
        super(MagicCADAIWidget, self).__init__(parent)
        self._controller = controller
        self._issues = []
        self._build_ui()
```

---

### Control Row

```python
def _build_ui(self):
    layout = QtWidgets.QVBoxLayout(self)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    
    controls = QtWidgets.QGridLayout()
    
    # Model selection
    controls.addWidget(QtWidgets.QLabel("Model"), 0, 0)
    self.model_combo = QtWidgets.QComboBox()
    for model in MODEL_OPTIONS:  # ("gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini")
        self.model_combo.addItem(model)
    self.model_combo.setCurrentIndex(0)
    controls.addWidget(self.model_combo, 0, 1)
    
    # Auto-validate toggle
    self.auto_validate = QtWidgets.QCheckBox("Real-time validation")
    self.auto_validate.setChecked(True)
    controls.addWidget(self.auto_validate, 0, 2)
    
    # Status label
    self.status_label = QtWidgets.QLabel("MagicCAD AI idle")
    self.status_label.setWordWrap(True)
    controls.addWidget(self.status_label, 1, 0, 1, 3)
    
    layout.addLayout(controls)
```

---

### Copilot Tab

```python
def _build_copilot_tab(self):
    tab = QtWidgets.QWidget()
    tab_layout = QtWidgets.QVBoxLayout(tab)
    tab_layout.setContentsMargins(4, 4, 4, 4)
    tab_layout.setSpacing(6)
    
    # Action buttons
    button_row = QtWidgets.QHBoxLayout()
    self.validate_document_button = QtWidgets.QPushButton("Validate Document")
    self.validate_selection_button = QtWidgets.QPushButton("Validate Selection")
    self.run_copilot_button = QtWidgets.QPushButton("Run Copilot")
    button_row.addWidget(self.validate_document_button)
    button_row.addWidget(self.validate_selection_button)
    button_row.addWidget(self.run_copilot_button)
    tab_layout.addLayout(button_row)
    
    # Prompt input
    self.prompt_input = QtWidgets.QPlainTextEdit()
    if hasattr(self.prompt_input, "setPlaceholderText"):
        self.prompt_input.setPlaceholderText(
            "Ask for a review, design guidance, or a draft change. "
            "Example: Create a gear with 10 teeth, 2 mm module, 8 mm thickness, and 6 mm center bore."
        )
    self.prompt_input.setMaximumHeight(110)
    tab_layout.addWidget(self.prompt_input)
    
    # Transcript (AI conversation)
    self.transcript = QtWidgets.QPlainTextEdit()
    self.transcript.setReadOnly(True)
    tab_layout.addWidget(self.transcript, 1)
    
    self.tabs.addTab(tab, "Copilot")
```

**Components:**
- **Validate Document**: Run full validation
- **Validate Selection**: Run validation on selected objects only
- **Run Copilot**: Ask AI a question
- **Prompt Input**: User's question/request
- **Transcript**: AI responses stream here

---

### Issues Tab

```python
def _build_issues_tab(self):
    tab = QtWidgets.QWidget()
    tab_layout = QtWidgets.QVBoxLayout(tab)
    tab_layout.setContentsMargins(4, 4, 4, 4)
    tab_layout.setSpacing(6)
    
    # Splitter for list + details
    splitter = QtWidgets.QSplitter(Qt.Vertical)
    self.issue_list = QtWidgets.QListWidget()
    self.issue_details = QtWidgets.QTextBrowser()
    splitter.addWidget(self.issue_list)
    splitter.addWidget(self.issue_details)
    splitter.setStretchFactor(0, 2)
    splitter.setStretchFactor(1, 3)
    tab_layout.addWidget(splitter, 1)
    
    # Action buttons
    issue_buttons = QtWidgets.QHBoxLayout()
    self.highlight_issue_button = QtWidgets.QPushButton("Highlight")
    self.clear_highlight_button = QtWidgets.QPushButton("Clear Highlight")
    issue_buttons.addWidget(self.highlight_issue_button)
    issue_buttons.addWidget(self.clear_highlight_button)
    tab_layout.addLayout(issue_buttons)
    
    self.tabs.addTab(tab, "Issues")
```

**Components:**
- **Issue List**: Clickable list of validation issues
- **Issue Details**: Full details of selected issue
- **Highlight**: Highlight affected geometry in 3D view
- **Clear Highlight**: Remove highlighting

---

### Report Tab

```python
def _build_report_tab(self):
    tab = QtWidgets.QWidget()
    tab_layout = QtWidgets.QVBoxLayout(tab)
    tab_layout.setContentsMargins(4, 4, 4, 4)
    tab_layout.setSpacing(6)
    
    # Report display
    self.report_browser = QtWidgets.QTextBrowser()
    tab_layout.addWidget(self.report_browser, 1)
    
    # Action buttons
    report_buttons = QtWidgets.QHBoxLayout()
    self.apply_button = QtWidgets.QPushButton("Apply Draft")
    self.revise_button = QtWidgets.QPushButton("Revise Draft")
    self.reject_button = QtWidgets.QPushButton("Reject Draft")
    self.export_button = QtWidgets.QPushButton("Export Report")
    report_buttons.addWidget(self.apply_button)
    report_buttons.addWidget(self.revise_button)
    report_buttons.addWidget(self.reject_button)
    report_buttons.addWidget(self.export_button)
    tab_layout.addLayout(report_buttons)
    
    self.tabs.addTab(tab, "Report")
```

**Components:**
- **Report Browser**: Markdown/HTML report display
- **Apply Draft**: Approve and apply AI's proposed changes
- **Revise Draft**: Send feedback for revision
- **Reject Draft**: Discard proposed changes
- **Export Report**: Save report to file

---

## DockPanel Controller

```python
class DockPanelController:
    """Manages the dock panel lifecycle and event handling."""
    
    _instance = None
    
    @classmethod
    def get_controller(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self._dock = None
        self._widget = None
        self._bridge = BridgeClient.SidecarBridgeClient()
        self._observers = None
        self._current_run_id = None
        self._pending_changes = None
        self._last_snapshot = None
        
        self._setup_connections()
```

---

## Event Handling

### SSE Event Handler

```python
def _handle_event(self, event):
    """Handle incoming SSE event from sidecar."""
    event_name = event.get("event", "")
    
    if event_name == "run_started":
        self._handle_run_started(event)
    
    elif event_name == "node_status":
        self._handle_node_status(event)
    
    elif event_name == "assistant_delta":
        self._handle_assistant_delta(event)
    
    elif event_name == "issues_delta":
        self._handle_issues_delta(event)
    
    elif event_name == "approval_required":
        self._handle_approval_required(event)
    
    elif event_name == "tool_request":
        self._handle_tool_request(event)
    
    elif event_name == "report_ready":
        self._handle_report_ready(event)
    
    elif event_name == "run_finished":
        self._handle_run_finished(event)
    
    elif event_name == "run_error":
        self._handle_run_error(event)
```

---

### Handle Validation Start

```python
def _handle_run_started(self, event):
    """Run started - update status."""
    status = event.get("status", "running")
    self._widget.set_status("Validation started: {0}".format(status))
    self._widget.clear_transcript()
```

---

### Handle Node Status

```python
def _handle_node_status(self, event):
    """Graph node status update."""
    node = event.get("node", "")
    status = event.get("status", "")
    self._widget.set_status("Running: {0} ({1})".format(node, status))
```

**Example Status Updates:**
- "Running: intake (running)"
- "Running: deterministic_validate (completed)"
- "Running: llm_explain (running)"

---

### Handle AI Response

```python
def _handle_assistant_delta(self, event):
    """AI explanation text received."""
    text = event.get("text", "")
    phase = event.get("phase", "")
    
    if text:
        self._widget.append_transcript(text)
        self._widget.set_status("AI response received")
```

---

### Handle Issues

```python
def _handle_issues_delta(self, event):
    """Validation issues received."""
    issues = event.get("issues", [])
    self._widget.set_issues(issues)
    self._issues = issues
    
    count = len(issues)
    if count > 0:
        self._widget.set_status("Found {0} issues".format(count))
        self._widget.tabs.setCurrentIndex(1)  # Switch to Issues tab
```

---

### Handle Approval Required

```python
def _handle_approval_required(self, event):
    """User approval needed for proposed changes."""
    proposed_changes = event.get("proposed_changes", [])
    self._pending_changes = proposed_changes
    
    # Enable approval buttons
    self._widget.apply_button.setEnabled(True)
    self._widget.reject_button.setEnabled(True)
    self._widget.revise_button.setEnabled(True)
    
    # Show change summary
    summary = "\n".join(change.get("summary", "") for change in proposed_changes)
    self._widget.report_browser.setHtml("""
        <h3>Proposed Changes</h3>
        <p>{0}</p>
        <p><i>Click 'Apply Draft' to approve, 'Reject Draft' to discard, 
        or 'Revise Draft' to request changes.</i></p>
    """.format(summary))
    
    self._widget.set_status("Approval required: Review proposed changes")
    self._widget.tabs.setCurrentIndex(2)  # Switch to Report tab
```

---

### Handle Tool Request

```python
def _handle_tool_request(self, event):
    """AI requested a tool execution."""
    tool_request = event.get("request", {})
    return_node = event.get("return_node", "")
    
    # Execute tool
    result = ToolRegistry.execute_tool_request(tool_request)
    
    # Send results back to sidecar
    self._bridge.submit_tool_results(
        self._current_run_id,
        {"tool_result": result, "return_to": return_node}
    )
```

---

### Handle Report Ready

```python
def _handle_report_ready(self, event):
    """Final report ready."""
    report = event.get("report", {})
    
    # Display report
    html = report.get("html", "")
    if html:
        self._widget.report_browser.setHtml(html)
    
    # Save to document
    root, session, report_obj = SessionObjects.ensure_storage()
    if report_obj:
        SessionObjects.update_report(report_obj, report)
    
    self._widget.set_status("Report generated")
```

---

### Handle Run Finished

```python
def _handle_run_finished(self, event):
    """Run completed."""
    status = event.get("status", "completed")
    self._widget.set_status("Validation {0}".format(status))
    
    # Disable approval buttons if no pending changes
    if not self._pending_changes:
        self._widget.apply_button.setEnabled(False)
        self._widget.reject_button.setEnabled(False)
        self._widget.revise_button.setEnabled(False)
```

---

### Handle Error

```python
def _handle_run_error(self, event):
    """Run error occurred."""
    message = event.get("message", "Unknown error")
    traceback_text = event.get("traceback", "")
    
    self._widget.set_status("Error: {0}".format(message))
    self._widget.append_transcript("Error: {0}".format(message))
    
    if traceback_text:
        FreeCAD.Console.PrintError(traceback_text)
```

---

## Validation Commands

### Validate Document

```python
def validate_document(self, selection_only=False, intent="validate"):
    """Run validation on document or selection."""
    document = FreeCAD.ActiveDocument
    if document is None:
        self._set_status("No active document")
        return
    
    # Build snapshot
    snapshot = Snapshot.build_document_snapshot(
        document=document, 
        selection_only=selection_only
    )
    if not snapshot:
        self._set_status("Failed to build a document snapshot")
        return
    
    self._last_snapshot = snapshot
    
    # Prepare payload
    payload = {
        "model": self._widget.current_model(),
        "intent": intent,
        "prompt": self._widget.current_prompt(),
        "selection_only": selection_only,
        "snapshot": snapshot,
    }
    
    # Send to sidecar
    response = self._bridge.start_run(payload)
    if response:
        self._current_run_id = response.get("run_id", "")
        
        # Save session info
        root, session, report_obj = SessionObjects.ensure_storage()
        if session:
            SessionObjects.update_session(
                session,
                run_id=self._current_run_id,
                model=payload["model"],
                snapshot_hash=snapshot.get("snapshot_hash", ""),
            )
```

---

### Apply Pending Draft

```python
def apply_pending_draft(self):
    """Apply approved changes."""
    if not self._pending_changes:
        self._set_status("No pending changes to apply")
        return
    
    change = self._pending_changes[0]  # Use first change
    
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

### Export Report

```python
def export_report(self):
    """Export report to file."""
    document = FreeCAD.ActiveDocument
    if document is None:
        return
    
    # Get report from document
    root, session, report_obj = SessionObjects.ensure_storage()
    if not report_obj or not report_obj.Payload:
        self._set_status("No report to export")
        return
    
    # File dialog
    default_name = "{0}_MagicCAD_Report.md".format(document.Label)
    file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
        None,
        "Export MagicCAD Report",
        default_name,
        "Markdown Files (*.md);;HTML Files (*.html);;All Files (*)"
    )
    
    file_path = _normalize_save_path(file_path)
    if not file_path:
        return
    
    # Export
    try:
        if file_path.endswith(".html"):
            content = report_obj.Html
        else:
            content = report_obj.Markdown
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        self._set_status("Report exported to {0}".format(file_path))
    except Exception as exc:
        self._set_status("Export failed: {0}".format(exc))
```

---

## Observers Integration

```python
def _setup_connections(self):
    """Connect UI buttons to handlers."""
    self._widget.validate_document_button.clicked.connect(
        lambda: self.validate_document(selection_only=False, intent="validate")
    )
    self._widget.validate_selection_button.clicked.connect(
        lambda: self.validate_document(selection_only=True, intent="validate")
    )
    self._widget.run_copilot_button.clicked.connect(
        lambda: self.run_copilot()
    )
    self._widget.apply_button.clicked.connect(self.apply_pending_draft)
    self._widget.revise_button.clicked.connect(self.revise_pending_draft)
    self._widget.reject_button.clicked.connect(self.reject_pending_draft)
    self._widget.export_button.clicked.connect(self.export_report)
    self._widget.highlight_issue_button.clicked.connect(self.highlight_current_issue)
    self._widget.clear_highlight_button.clicked.connect(self.clear_highlight)
    self._widget.issue_list.currentRowChanged.connect(self.on_issue_selected)
```

---

## Real-Time Validation

```python
def on_document_event(self, reason, document):
    """Handle document change event."""
    if not self._widget.auto_validate_enabled():
        return
    
    if reason in ("created_object", "changed_object", "recomputed_object"):
        # Debounced validation trigger
        self._validate_timer.start(1000)  # 1 second debounce

def _on_validate_timer(self):
    """Trigger validation after debounce."""
    self.validate_document(selection_only=True, intent="validate")
```

---

## Issue Highlighting

```python
def highlight_current_issue(self):
    """Highlight geometry for selected issue."""
    issue = self._widget.current_issue()
    if not issue:
        return
    
    object_ref = issue.get("object_ref", {})
    object_name = object_ref.get("object_name", "")
    subelement_ref = issue.get("subelement_ref", {})
    
    Highlighting.highlight(object_name, subelement_ref)

def clear_highlight(self):
    """Clear all highlighting."""
    Highlighting.clear()
```

---

## Panel Lifecycle

```python
def show_panel(self):
    """Show the dock panel."""
    if self._dock is None:
        self._create_dock()
    self._dock.show()

def _create_dock(self):
    """Create the dock widget."""
    self._widget = MagicCADAIWidget(self)
    
    self._dock = FreeCADGui.createDockWidget(
        "MagicCADAI",
        self._widget,
        "MagicCAD AI",
    )
    self._dock.setAllowedAreas(
        QtCore.Qt.RightDockWidgetArea | QtCore.Qt.LeftDockWidgetArea
    )
    
    # Start observers
    self._observers = ObserverBundle(self)
    self._observers.start()
```

---

## Related Documents

- `02_data_flow.md` - UI in data flow
- `07_approval_system.md` - Approval UI
- `08_observers.md` - Change observers
- `09_highlighting.md` - Issue highlighting
