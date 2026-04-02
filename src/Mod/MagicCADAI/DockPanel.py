# SPDX-License-Identifier: LGPL-2.1-or-later

import datetime
import json
import os
import time

import FreeCAD
import FreeCADGui

import BridgeClient
import Highlighting
import Observers
import QtCompat
import SessionObjects
import Snapshot
import ToolRegistry


QtCore = QtCompat.QtCore
QtWidgets = QtCompat.QtWidgets
Qt = QtCompat.Qt

MODEL_OPTIONS = (
    # Gemini models (recommended)
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    # OpenAI models
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.4-mini",
)


def _normalize_save_path(path_result):
    if isinstance(path_result, tuple):
        path_result = path_result[0]
    return str(path_result) if path_result else ""


def _utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class MagicCADAIWidget(QtWidgets.QWidget):
    def __init__(self, controller, parent=None):
        super(MagicCADAIWidget, self).__init__(parent)
        self._controller = controller
        self._issues = []
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QtWidgets.QGridLayout()
        controls.setHorizontalSpacing(8)
        controls.setVerticalSpacing(6)

        controls.addWidget(QtWidgets.QLabel("Model"), 0, 0)
        self.model_combo = QtWidgets.QComboBox()
        for model in MODEL_OPTIONS:
            self.model_combo.addItem(model)
        self.model_combo.setCurrentIndex(0)
        controls.addWidget(self.model_combo, 0, 1)

        self.auto_validate = QtWidgets.QCheckBox("Real-time validation")
        self.auto_validate.setChecked(True)
        controls.addWidget(self.auto_validate, 0, 2)

        self.status_label = QtWidgets.QLabel("MagicCAD AI idle")
        self.status_label.setWordWrap(True)
        controls.addWidget(self.status_label, 1, 0, 1, 3)
        layout.addLayout(controls)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._build_copilot_tab()
        self._build_issues_tab()
        self._build_report_tab()

    def _build_copilot_tab(self):
        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        tab_layout.setContentsMargins(4, 4, 4, 4)
        tab_layout.setSpacing(6)

        button_row = QtWidgets.QHBoxLayout()
        self.validate_document_button = QtWidgets.QPushButton("Validate Document")
        self.validate_selection_button = QtWidgets.QPushButton("Validate Selection")
        self.run_copilot_button = QtWidgets.QPushButton("Run Copilot")
        button_row.addWidget(self.validate_document_button)
        button_row.addWidget(self.validate_selection_button)
        button_row.addWidget(self.run_copilot_button)
        tab_layout.addLayout(button_row)

        self.prompt_input = QtWidgets.QPlainTextEdit()
        if hasattr(self.prompt_input, "setPlaceholderText"):
            self.prompt_input.setPlaceholderText(
                "Ask for a review, design guidance, or a draft change. Example: Create a gear with 10 teeth, 2 mm module, 8 mm thickness, and 6 mm center bore."
            )
        self.prompt_input.setMaximumHeight(110)
        tab_layout.addWidget(self.prompt_input)

        self.transcript = QtWidgets.QPlainTextEdit()
        self.transcript.setReadOnly(True)
        tab_layout.addWidget(self.transcript, 1)
        self.tabs.addTab(tab, "Copilot")

    def _build_issues_tab(self):
        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        tab_layout.setContentsMargins(4, 4, 4, 4)
        tab_layout.setSpacing(6)

        splitter = QtWidgets.QSplitter(Qt.Vertical)
        self.issue_list = QtWidgets.QListWidget()
        self.issue_details = QtWidgets.QTextBrowser()
        splitter.addWidget(self.issue_list)
        splitter.addWidget(self.issue_details)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        tab_layout.addWidget(splitter, 1)

        issue_buttons = QtWidgets.QHBoxLayout()
        self.highlight_issue_button = QtWidgets.QPushButton("Highlight")
        self.clear_highlight_button = QtWidgets.QPushButton("Clear Highlight")
        issue_buttons.addWidget(self.highlight_issue_button)
        issue_buttons.addWidget(self.clear_highlight_button)
        tab_layout.addLayout(issue_buttons)
        self.tabs.addTab(tab, "Issues")

    def _build_report_tab(self):
        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        tab_layout.setContentsMargins(4, 4, 4, 4)
        tab_layout.setSpacing(6)

        self.report_browser = QtWidgets.QTextBrowser()
        tab_layout.addWidget(self.report_browser, 1)

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

    def current_model(self):
        return str(self.model_combo.currentText())

    def current_prompt(self):
        return str(self.prompt_input.toPlainText())

    def auto_validate_enabled(self):
        return self.auto_validate.isChecked()

    def set_status(self, text):
        self.status_label.setText(text)

    def append_transcript(self, text):
        if not text:
            return
        self.transcript.appendPlainText(text)

    def clear_transcript(self):
        self.transcript.clear()

    def set_issues(self, issues):
        self._issues = list(issues or [])
        self.issue_list.clear()
        for index, issue in enumerate(self._issues):
            label = "[{0}] {1}".format(issue.get("severity", "low").upper(), issue.get("message", ""))
            item = QtWidgets.QListWidgetItem(label)
            item.setData(Qt.UserRole, index)
            self.issue_list.addItem(item)
        if self._issues:
            self.issue_list.setCurrentRow(0)
        else:
            self.issue_details.setHtml("<p>No issues detected.</p>")

    def current_issue(self):
        row = self.issue_list.currentRow()
        if row < 0 or row >= len(self._issues):
            return None
        return self._issues[row]

    def show_issue_details(self, issue):
        if not issue:
            self.issue_details.setHtml("<p>Select an issue to inspect it.</p>")
            return
        html = [
            "<h3>{0}</h3>".format(issue.get("message", "")),
            "<p><b>Severity:</b> {0}</p>".format(issue.get("severity", "")),
            "<p><b>Category:</b> {0}</p>".format(issue.get("category", "")),
            "<p><b>Recommendation:</b> {0}</p>".format(issue.get("recommended_fix", "")),
        ]
        evidence = issue.get("evidence", {})
        if evidence:
            html.append("<pre>{0}</pre>".format(json.dumps(evidence, indent=2, sort_keys=True)))
        self.issue_details.setHtml("".join(html))

    def set_report(self, report):
        if not report:
            self.report_browser.setHtml("<p>No report available.</p>")
            return
        html = report.get("html", "")
        if html:
            self.report_browser.setHtml(html)
        else:
            self.report_browser.setPlainText(report.get("markdown", ""))

    def set_draft_state(self, can_apply, can_revise, can_reject):
        self.apply_button.setEnabled(bool(can_apply))
        self.revise_button.setEnabled(bool(can_revise))
        self.reject_button.setEnabled(bool(can_reject))


class MagicCADAIController(QtCore.QObject):
    def __init__(self, parent=None):
        super(MagicCADAIController, self).__init__(parent)
        self._dock = None
        self._widget = None
        self._bridge = BridgeClient.SidecarBridgeClient(self)
        self._bridge.statusChanged.connect(self._on_bridge_status)
        self._bridge.eventReceived.connect(self._on_bridge_event)
        self._bridge.bridgeError.connect(self._on_bridge_error)
        self._observers = Observers.ObserverBundle(self)
        self._highlight_manager = Highlighting.HighlightManager()
        self._initialized = False
        self._running_run_id = ""
        self._pending_approval = None
        self._last_snapshot = None
        self._last_report = None
        self._last_document_name = ""
        self._last_auto_validation_at = 0.0
        self._auto_validation_hold_until = 0.0

    def ensure_initialized(self):
        if self._initialized:
            return
        self._observers.start()
        self._initialized = True

    def show_panel(self):
        self.ensure_initialized()
        if self._dock is None:
            self._create_panel()
        self._dock.show()
        self._dock.raise_()
        self._dock.setVisible(True)
        return self._dock

    def on_document_event(self, reason, document):
        if not self._should_auto_validate(document):
            return
        if reason in ("changed_object", "recomputed_object", "recomputed_document", "undo", "redo"):
            self._last_auto_validation_at = time.time()
            self.validate_document(document=document, selection_only=False, intent="validate", prompt="", auto=True)

    def on_selection_event(self, reason, document):
        if not self._should_auto_validate(document):
            return
        if reason in ("add_selection", "remove_selection", "set_selection", "clear_selection"):
            self._last_auto_validation_at = time.time()
            self.validate_document(document=document, selection_only=True, intent="validate", prompt="", auto=True)

    def on_document_closed(self, document):
        if document and document.Name == self._last_document_name:
            self._last_document_name = ""
            self._last_snapshot = None
            self._last_report = None
            if self._widget is not None:
                self._widget.set_issues([])
                self._widget.set_report(None)
                self._widget.set_status("MagicCAD AI idle")

    def validate_document(self, document=None, selection_only=False, intent="validate", prompt=None, auto=False):
        document = document or FreeCAD.ActiveDocument
        if document is None:
            self._set_status("No active document to validate")
            return
        if self._running_run_id:
            self._set_status("A MagicCAD AI run is already in progress")
            return

        self.show_panel()
        snapshot = Snapshot.build_document_snapshot(document=document, selection_only=selection_only)
        if not snapshot:
            self._set_status("Failed to build a document snapshot")
            return

        _root, session, _report_obj = SessionObjects.ensure_storage(document)
        self._last_snapshot = snapshot
        self._last_document_name = document.Name
        prompt = self._widget.current_prompt().strip() if prompt is None else prompt
        if auto:
            prompt = ""

        request = {
            "thread_id": getattr(session, "ThreadId", ""),
            "previous_response_id": getattr(session, "PreviousResponseId", ""),
            "snapshot": snapshot,
            "intent": intent,
            "prompt": prompt,
            "model": self._widget.current_model(),
            "selection_only": selection_only,
            "requested_at": _utc_now(),
        }
        response = self._bridge.start_run(request)
        if response is None:
            self._set_status("Failed to start MagicCAD AI run")
            return

        self._running_run_id = response.get("run_id", "")
        self._pending_approval = None
        SessionObjects.update_session(
            session,
            thread_id=response.get("thread_id", ""),
            run_id=response.get("run_id", ""),
            model=request["model"],
            status="running",
            snapshot_hash=snapshot.get("snapshot_hash", ""),
            payload={"intent": intent, "selection_only": selection_only, "auto": auto},
        )
        if not auto:
            self._widget.append_transcript(
                "Started {0} run {1} on {2}".format(intent, response.get("run_id", ""), document.Label)
            )
        self._widget.set_draft_state(False, False, False)
        self._set_status("MagicCAD AI run in progress...")

    def run_copilot(self):
        self.validate_document(selection_only=False, intent="copilot", prompt=self._widget.current_prompt(), auto=False)

    def apply_pending_draft(self):
        document = FreeCAD.ActiveDocument
        if document is None:
            self._set_status("No active document available")
            return

        if self._pending_approval:
            change_id = ""
            proposed_changes = self._pending_approval.get("proposed_changes", [])
            if proposed_changes:
                change_id = proposed_changes[0].get("change_id", "")
            self._bridge.resume_run(
                self._pending_approval.get("run_id", ""),
                "approve",
                {"change_id": change_id},
            )
            self._set_status("Approval sent to sidecar. Waiting for local tool request...")
            return

        self._set_status("No live draft approval is pending. Run the copilot again to apply a draft.")

    def revise_pending_draft(self):
        if not self._pending_approval:
            self._set_status("No pending draft to revise")
            return
        feedback = self._widget.current_prompt().strip()
        if not feedback:
            self._set_status("Enter revision feedback in the copilot box before revising the draft")
            return
        self._bridge.resume_run(
            self._pending_approval.get("run_id", ""),
            "edit",
            {"feedback": feedback},
        )
        self._set_status("Revision feedback sent to the sidecar")

    def reject_pending_draft(self):
        if not self._pending_approval:
            self._set_status("No pending draft to reject")
            return
        self._bridge.resume_run(self._pending_approval.get("run_id", ""), "reject", {})
        self._set_status("Rejected the pending draft")

    def export_report(self):
        document = FreeCAD.ActiveDocument
        if document is None:
            self._set_status("No active document available")
            return
        if self._last_report is None:
            _root, _session, report_obj = SessionObjects.ensure_storage(document)
            self._last_report = SessionObjects.report_payload(report_obj)
        if not self._last_report:
            self._set_status("No report available to export")
            return

        path = _normalize_save_path(
            QtWidgets.QFileDialog.getSaveFileName(
                self._dock,
                "Export MagicCAD AI Report",
                os.path.join(os.path.expanduser("~"), "magiccad-report.md"),
                "Markdown (*.md);;JSON (*.json)",
            )
        )
        if not path:
            return
        if path.endswith(".json"):
            content = json.dumps(self._last_report, indent=2, sort_keys=True)
        else:
            content = self._last_report.get("markdown", "")
        with open(path, "w") as handle:
            handle.write(content)
        self._set_status("Exported report to {0}".format(path))

    def highlight_current_issue(self):
        issue = self._widget.current_issue()
        if issue:
            self._highlight_manager.highlight_issue(issue)

    def clear_highlight(self):
        self._highlight_manager.clear()

    def _create_panel(self):
        self._widget = MagicCADAIWidget(self)
        self._widget.validate_document_button.clicked.connect(
            lambda: self.validate_document(selection_only=False, intent="validate")
        )
        self._widget.validate_selection_button.clicked.connect(
            lambda: self.validate_document(selection_only=True, intent="validate")
        )
        self._widget.run_copilot_button.clicked.connect(self.run_copilot)
        self._widget.highlight_issue_button.clicked.connect(self.highlight_current_issue)
        self._widget.clear_highlight_button.clicked.connect(self.clear_highlight)
        self._widget.apply_button.clicked.connect(self.apply_pending_draft)
        self._widget.revise_button.clicked.connect(self.revise_pending_draft)
        self._widget.reject_button.clicked.connect(self.reject_pending_draft)
        self._widget.export_button.clicked.connect(self.export_report)
        self._widget.issue_list.currentRowChanged.connect(lambda _row: self._widget.show_issue_details(self._widget.current_issue()))
        self._widget.issue_list.itemDoubleClicked.connect(lambda _item: self.highlight_current_issue())
        self._widget.set_draft_state(False, False, False)

        self._dock = QtWidgets.QDockWidget("MagicCAD AI")
        self._dock.setObjectName("MagicCADAIDock")
        self._dock.setWidget(self._widget)
        self._dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        FreeCADGui.getMainWindow().addDockWidget(Qt.RightDockWidgetArea, self._dock)

    def _on_bridge_status(self, status):
        self._set_status(status)

    def _on_bridge_error(self, context, message):
        self._widget.append_transcript("Bridge error [{0}]: {1}".format(context, message))
        self._set_status("MagicCAD AI bridge error")

    def _on_bridge_event(self, event):
        event_name = event.get("event", "")
        run_id = event.get("run_id", "")
        document = FreeCAD.ActiveDocument
        _root = session = report_obj = None
        if document is not None:
            _root, session, report_obj = SessionObjects.ensure_storage(document)

        if event_name == "run_started":
            self._running_run_id = run_id
            self._widget.append_transcript("Run {0} started".format(run_id))
            if session is not None:
                SessionObjects.update_session(session, run_id=run_id, status="running")
        elif event_name == "node_status":
            self._set_status("{0}: {1}".format(event.get("node", "node"), event.get("status", "")))
        elif event_name == "assistant_delta":
            self._widget.append_transcript(event.get("text", ""))
        elif event_name == "issues_delta":
            issues = event.get("issues", [])
            self._widget.set_issues(issues)
            self._widget.show_issue_details(self._widget.current_issue())
            self._widget.tabs.setCurrentIndex(1 if issues else 0)
        elif event_name == "approval_required":
            self._pending_approval = event
            self._widget.set_draft_state(True, True, True)
            self._widget.append_transcript(event.get("message", "Approval is required before applying the proposed change."))
            self._widget.tabs.setCurrentIndex(2)
        elif event_name == "tool_request":
            if not document:
                self._bridge.submit_tool_results(
                    run_id,
                    {"request_id": event.get("request_id", ""), "result": {"ok": False, "error": "No active document"}},
                )
                return
            self._auto_validation_hold_until = time.time() + 2.0
            result = ToolRegistry.execute_tool_request(event, document=document)
            self._bridge.submit_tool_results(
                run_id,
                {"request_id": event.get("request_id", ""), "result": result},
            )
            if result.get("ok", False):
                self._widget.append_transcript("Executed local tool request: {0}".format(event.get("tool_name", "")))
            else:
                self._widget.append_transcript("Local tool request failed: {0}".format(result.get("error", "")))
        elif event_name == "report_ready":
            report = event.get("report", {})
            self._last_report = report
            if report_obj is not None:
                SessionObjects.update_report(report_obj, report)
            if session is not None:
                SessionObjects.update_session(
                    session,
                    thread_id=report.get("thread_id", ""),
                    status="report_ready",
                    snapshot_hash=report.get("snapshot_hash", ""),
                    previous_response_id=report.get("previous_response_id", ""),
                    last_phase=report.get("assistant_phase", ""),
                )
            self._widget.set_report(report)
            self._widget.tabs.setCurrentIndex(2)
            has_pending = bool(self._pending_approval)
            self._widget.set_draft_state(has_pending, has_pending, has_pending)
        elif event_name == "run_error":
            self._widget.append_transcript("Run error: {0}".format(event.get("message", "")))
            if session is not None:
                SessionObjects.update_session(session, status="error")
        elif event_name == "run_finished":
            self._running_run_id = ""
            finished_status = event.get("status", "completed")
            self._set_status("Run {0} finished with status {1}".format(run_id, finished_status))
            if session is not None:
                SessionObjects.update_session(session, status=finished_status)
            if finished_status != "awaiting_approval":
                self._pending_approval = None
                self._widget.set_draft_state(False, False, False)

    def _set_status(self, text):
        if self._widget is not None:
            self._widget.set_status(text)

    def _should_auto_validate(self, document):
        if document is None or self._widget is None:
            return False
        if self._running_run_id:
            return False
        if not self._widget.auto_validate_enabled():
            return False
        if time.time() < self._auto_validation_hold_until:
            return False
        if time.time() - self._last_auto_validation_at < 1.5:
            return False
        return True


_controller_singleton = None


def get_controller():
    global _controller_singleton
    if _controller_singleton is None:
        _controller_singleton = MagicCADAIController()
    return _controller_singleton
