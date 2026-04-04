# SPDX-License-Identifier: LGPL-2.1-or-later

import datetime
import html as html_lib
import json
import os
import re
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
QtGui = QtCompat.QtGui
QtWidgets = QtCompat.QtWidgets
Qt = QtCompat.Qt
Signal = QtCompat.Signal

DEFAULT_MODEL = "gemini-2.5-flash"
MODEL_OPTIONS = (
    # Gemini models (recommended)
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    # Groq models
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "qwen/qwen3-32b",
    "openai/gpt-oss-20b",
    # OpenAI models
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.4-mini",
)


class MarkdownTextBrowser(QtWidgets.QTextBrowser):
    def __init__(self, parent=None):
        super(MarkdownTextBrowser, self).__init__(parent)
        self.setOpenExternalLinks(True)

    def set_markdown_text(self, text):
        text = text or ""
        geometry = self.geometry()
        if hasattr(super(MarkdownTextBrowser, self), "setMarkdown"):
            super(MarkdownTextBrowser, self).setMarkdown(text)
        else:
            try:
                import markdown

                self.setHtml(markdown.markdown(text, extensions=["fenced_code", "tables"]))
            except Exception:
                self.setPlainText(text)
        self.setGeometry(geometry)


class CopilotPromptInput(QtWidgets.QPlainTextEdit):
    def __init__(self, submit_callback, parent=None):
        super(CopilotPromptInput, self).__init__(parent)
        self._submit_callback = submit_callback

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            if self.toPlainText().strip():
                event.accept()
                self._submit_callback()
                return
        super(CopilotPromptInput, self).keyPressEvent(event)


def _escape_markdown_text(text):
    escaped = text or ""
    for char in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", "!", "|", ">"):
        escaped = escaped.replace(char, "\\" + char)
    return escaped


def _replace_camera_scalar(camera_text, field_name, value):
    pattern = r"(\b{0}\s+)([-+0-9.eE]+)".format(re.escape(field_name))
    replacement = r"\g<1>{0:.6f}".format(float(value))
    return re.sub(pattern, replacement, camera_text, count=1)


def _issue_markdown(issue):
    if not issue:
        return "Select an issue to inspect it."

    lines = [
        "### {0}".format(issue.get("message", "") or "Issue"),
        "",
        "**Severity:** {0}".format(issue.get("severity", "") or "unknown"),
        "",
        "**Category:** {0}".format(issue.get("category", "") or "uncategorized"),
    ]
    recommendation = issue.get("recommended_fix", "")
    if recommendation:
        lines.extend(["", "#### Recommendation", "", recommendation])
    evidence = issue.get("evidence", {})
    if evidence:
        lines.extend(
            [
                "",
                "#### Evidence",
                "",
                "```json",
                json.dumps(evidence, indent=2, sort_keys=True),
                "```",
            ]
        )
    return "\n".join(lines)


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
        self._transcript_sections = []
        self._build_ui()
        self._apply_cursor_style()

    def _build_ui(self):
        self.setObjectName("magiccadPanel")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        self.auto_validate = QtWidgets.QCheckBox("Live")
        self.auto_validate.setChecked(True)
        self.auto_validate.hide()

        self.status_label = QtWidgets.QLabel("")
        self.status_label.hide()

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        self._build_copilot_tab()
        self._build_issues_tab()
        self._build_report_tab()

    def _build_copilot_tab(self):
        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        tab_layout.setContentsMargins(2, 4, 2, 2)
        tab_layout.setSpacing(8)

        self.transcript = MarkdownTextBrowser()
        self.transcript.setObjectName("transcriptView")
        self.transcript.setReadOnly(True)
        tab_layout.addWidget(self.transcript, 1)

        composer_card = QtWidgets.QFrame()
        composer_card.setObjectName("composerCard")
        composer_layout = QtWidgets.QVBoxLayout(composer_card)
        composer_layout.setContentsMargins(8, 8, 8, 8)
        composer_layout.setSpacing(8)

        self.prompt_input = CopilotPromptInput(self._controller.run_copilot)
        self.prompt_input.setObjectName("composer")
        if hasattr(self.prompt_input, "setPlaceholderText"):
            self.prompt_input.setPlaceholderText("Describe what to build")
        self.prompt_input.setMinimumHeight(72)
        self.prompt_input.setMaximumHeight(110)
        composer_layout.addWidget(self.prompt_input)

        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.setSpacing(8)
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setObjectName("footerCombo")
        for model in MODEL_OPTIONS:
            self.model_combo.addItem(model)
        self.set_current_model(DEFAULT_MODEL)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        bottom_row.addWidget(self.model_combo)
        self.run_copilot_button = QtWidgets.QPushButton("Submit")
        self.run_copilot_button.setObjectName("primaryButton")
        self.run_copilot_button.setEnabled(False)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.run_copilot_button)
        composer_layout.addLayout(bottom_row)
        tab_layout.addWidget(composer_card)
        self.tabs.addTab(tab, "Copilot")
        self.prompt_input.textChanged.connect(self._update_copilot_submit_state)

    def _build_issues_tab(self):
        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        tab_layout.setContentsMargins(6, 6, 6, 6)
        tab_layout.setSpacing(8)

        splitter = QtWidgets.QSplitter(Qt.Vertical)
        self.issue_list = QtWidgets.QListWidget()
        self.issue_list.setObjectName("issueList")
        self.issue_details = MarkdownTextBrowser()
        self.issue_details.setObjectName("detailsView")
        splitter.addWidget(self.issue_list)
        splitter.addWidget(self.issue_details)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        tab_layout.addWidget(splitter, 1)

        issue_buttons = QtWidgets.QHBoxLayout()
        self.highlight_issue_button = QtWidgets.QPushButton("Highlight")
        self.highlight_issue_button.setObjectName("secondaryButton")
        self.clear_highlight_button = QtWidgets.QPushButton("Clear Highlight")
        self.clear_highlight_button.setObjectName("ghostButton")
        issue_buttons.addWidget(self.highlight_issue_button)
        issue_buttons.addWidget(self.clear_highlight_button)
        tab_layout.addLayout(issue_buttons)
        self.tabs.addTab(tab, "Issues")

    def _build_report_tab(self):
        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        tab_layout.setContentsMargins(6, 6, 6, 6)
        tab_layout.setSpacing(8)

        self.approval_notice = QtWidgets.QLabel("")
        self.approval_notice.setObjectName("approvalNotice")
        self.approval_notice.setWordWrap(True)
        self.approval_notice.hide()
        tab_layout.addWidget(self.approval_notice)

        self.report_browser = MarkdownTextBrowser()
        self.report_browser.setObjectName("reportView")
        tab_layout.addWidget(self.report_browser, 1)

        report_buttons = QtWidgets.QHBoxLayout()
        report_buttons.setSpacing(8)
        self.apply_button = QtWidgets.QPushButton("Apply Draft")
        self.apply_button.setObjectName("primaryButton")
        self.revise_button = QtWidgets.QPushButton("Revise Draft")
        self.revise_button.setObjectName("secondaryButton")
        self.reject_button = QtWidgets.QPushButton("Reject Draft")
        self.reject_button.setObjectName("ghostButton")
        self.export_button = QtWidgets.QPushButton("Export Report")
        self.export_button.setObjectName("ghostButton")
        report_buttons.addWidget(self.apply_button)
        report_buttons.addWidget(self.revise_button)
        report_buttons.addWidget(self.reject_button)
        report_buttons.addWidget(self.export_button)
        tab_layout.addLayout(report_buttons)
        self.tabs.addTab(tab, "Report")

    def _apply_cursor_style(self):
        self.setFont(QtGui.QFont())

        code_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        code_font.setPointSize(10)
        self.transcript.document().setDefaultFont(code_font)
        self.issue_details.document().setDefaultFont(code_font)
        self.report_browser.document().setDefaultFont(code_font)

        self.setStyleSheet(
            """
            QWidget#magiccadPanel {
                background: #171717;
                color: #e8e8e8;
            }
            QLabel#approvalNotice {
                background: #1d1d1d;
                border: 1px solid #343434;
                border-radius: 8px;
                color: #d7d7d7;
                padding: 8px 10px;
            }
            QFrame#composerCard {
                background: #1d1d1d;
                border: 1px solid #2b2b2b;
                border-radius: 10px;
            }
            QComboBox#modelCombo, QComboBox#footerCombo, QPlainTextEdit#composer, QListWidget#issueList,
            QTextBrowser#transcriptView, QTextBrowser#detailsView, QTextBrowser#reportView {
                background: #1b1b1b;
                border: 1px solid #2a2a2a;
                border-radius: 8px;
                color: #e8e8e8;
                selection-background-color: #2b4f73;
            }
            QComboBox#modelCombo, QComboBox#footerCombo {
                min-height: 26px;
                min-width: 112px;
                padding: 0 8px;
                background: #1b1b1b;
            }
            QPlainTextEdit#composer {
                border: none;
                background: #1d1d1d;
                padding: 4px 2px;
            }
            QListWidget#issueList, QTextBrowser#transcriptView, QTextBrowser#detailsView, QTextBrowser#reportView {
                padding: 6px;
            }
            QListWidget#issueList::item {
                border-radius: 6px;
                margin: 2px 0;
                padding: 7px 9px;
            }
            QListWidget#issueList::item:selected {
                background: #242424;
                color: #ffffff;
            }
            QPushButton {
                min-height: 28px;
                border-radius: 8px;
                padding: 0 10px;
                font-weight: 600;
            }
            QPushButton#primaryButton {
                background: #2a2a2a;
                border: 1px solid #3a3a3a;
                color: #ffffff;
            }
            QPushButton#primaryButton:hover {
                background: #323232;
            }
            QPushButton#secondaryButton {
                background: #1f1f1f;
                border: 1px solid #303030;
                color: #cfcfcf;
            }
            QPushButton#ghostButton {
                background: #181818;
                border: 1px solid #2a2a2a;
                color: #9a9a9a;
            }
            QPushButton#secondaryButton:hover, QPushButton#ghostButton:hover {
                background: #272727;
                border-color: #3a3a3a;
            }
            QPushButton:disabled {
                background: #171717;
                border-color: #242424;
                color: #666666;
            }
            QTabWidget::pane {
                border: none;
                background: #171717;
                margin-top: 0;
            }
            QTabBar::tab {
                background: transparent;
                color: #878787;
                padding: 6px 10px;
                margin-right: 6px;
                border-bottom: 1px solid transparent;
                font-weight: 700;
            }
            QTabBar::tab:selected {
                color: #efefef;
                border-bottom-color: #5d5d5d;
            }
            QScrollBar:vertical {
                background: #171717;
                width: 8px;
                margin: 4px 0;
            }
            QScrollBar::handle:vertical {
                background: #3a3a3a;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )

    def current_model(self):
        return str(self.model_combo.currentText())

    def set_current_model(self, model_name):
        model_name = str(model_name or "").strip()
        if not model_name:
            model_name = DEFAULT_MODEL
        index = self.model_combo.findText(model_name)
        if index < 0:
            index = self.model_combo.findText(DEFAULT_MODEL)
        if index < 0:
            index = 0
        self.model_combo.setCurrentIndex(index)

    def _on_model_changed(self, text):
        """Track when user manually changes the model selection."""
        if self._controller is not None:
            self._controller._user_selected_model = True

    def current_prompt(self):
        return str(self.prompt_input.toPlainText())

    def _update_copilot_submit_state(self):
        self.run_copilot_button.setEnabled(bool(self.current_prompt().strip()))

    def auto_validate_enabled(self):
        return self.auto_validate.isChecked()

    def set_status(self, text):
        self.status_label.setText(text)

    def append_transcript(self, text, markdown=False):
        if not text:
            return
        if markdown:
            section = "### Assistant\n\n{0}".format(text)
        else:
            section = "### System\n\n{0}".format(_escape_markdown_text(text))
        self._transcript_sections.append(section)
        self.transcript.set_markdown_text("\n\n---\n\n".join(self._transcript_sections))

    def append_user_transcript(self, text):
        if not text:
            return
        section = "### You\n\n{0}".format(_escape_markdown_text(text))
        self._transcript_sections.append(section)
        self.transcript.set_markdown_text("\n\n---\n\n".join(self._transcript_sections))

    def clear_transcript(self):
        self._transcript_sections = []
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
            self.issue_details.set_markdown_text("No issues detected.")

    def current_issue(self):
        row = self.issue_list.currentRow()
        if row < 0 or row >= len(self._issues):
            return None
        return self._issues[row]

    def show_issue_details(self, issue):
        self.issue_details.set_markdown_text(_issue_markdown(issue))

    def set_approval_notice(self, text):
        text = (text or "").strip()
        self.approval_notice.setText(text)
        self.approval_notice.setVisible(bool(text))

    def set_report(self, report):
        if not report:
            self.report_browser.set_markdown_text("No report available.")
            return
        markdown = report.get("markdown", "")
        html = report.get("html", "")
        if markdown:
            self.report_browser.set_markdown_text(markdown)
        elif html:
            self.report_browser.setHtml(html)
        else:
            self.report_browser.setHtml("<pre>{0}</pre>".format(html_lib.escape(json.dumps(report, indent=2, sort_keys=True))))

    def set_draft_state(self, can_apply, can_revise, can_reject):
        self.apply_button.setEnabled(bool(can_apply))
        self.revise_button.setEnabled(bool(can_revise))
        self.reject_button.setEnabled(bool(can_reject))


class MagicCADAIController(QtCore.QObject):
    toolRequestQueued = Signal(dict, str)

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
        self._run_meta = {}
        self._handled_tool_request_ids = set()
        self._last_snapshot = None
        self._last_report = None
        self._last_document_name = ""
        self._last_auto_validation_at = 0.0
        self._auto_validation_hold_until = 0.0
        self._user_selected_model = False
        self.toolRequestQueued.connect(self._execute_tool_request_on_gui_thread)

    def _log_debug(self, message, **payload):
        try:
            log_path = os.path.join(self._project_root(), "magiccadai.log")
            line = "{0} INFO [DockPanel] {1}".format(
                datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                message,
            )
            if payload:
                line += " | " + json.dumps(payload, sort_keys=True, default=str)
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass

    def _project_root(self):
        current = os.path.abspath(os.path.dirname(__file__))
        while current and current != os.path.dirname(current):
            if os.path.exists(os.path.join(current, "pixi.toml")):
                return current
            current = os.path.dirname(current)
        return os.path.abspath(os.getcwd())

    def _provider_for_model(self, model_name):
        model_name = str(model_name or "").strip().lower()
        if model_name.startswith("gemini"):
            return "gemini"
        if model_name.startswith(("llama-", "meta-llama/", "qwen/", "openai/gpt-oss-", "groq/")):
            return "groq"
        return "openai"

    def _sync_model_from_document(self, document=None):
        if self._widget is None:
            return
        # Don't override user's manual model selection from session data
        if self._user_selected_model:
            return
        document = document or FreeCAD.ActiveDocument
        if document is None:
            self._widget.set_current_model(DEFAULT_MODEL)
            return
        _root, session, _report_obj = SessionObjects.ensure_storage(document)
        session_model = getattr(session, "ModelName", "") if session is not None else ""
        self._widget.set_current_model(session_model or DEFAULT_MODEL)

    def _iter_created_object_names(self, tool_result):
        result = tool_result or {}
        for entry in result.get("results", []) or []:
            payload = entry.get("result", {}) or {}
            for name in payload.get("created", []) or []:
                if name:
                    yield name
            result_object = payload.get("result_object", "")
            if result_object:
                yield result_object

    def _format_tool_request_text(self, event):
        tool_name = str(event.get("tool_name", "") or "tool")
        arguments = event.get("arguments", {}) or {}
        if arguments:
            try:
                payload = json.dumps(arguments, sort_keys=True)
            except Exception:
                payload = repr(arguments)
            return "Tool call: {0}({1})".format(tool_name, payload)
        return "Tool call: {0}()".format(tool_name)

    def _format_tool_result_text(self, event, result):
        tool_name = str(event.get("tool_name", "") or "tool")
        if not result.get("ok", False):
            return "Tool result: {0} failed: {1}".format(tool_name, result.get("error", "unknown error"))
        created = []
        for name in self._iter_created_object_names(result):
            if name and name not in created:
                created.append(name)
        if created:
            return "Tool result: {0} created {1}.".format(tool_name, ", ".join(created))
        return "Tool result: {0} completed successfully.".format(tool_name)

    def _created_objects_max_extent(self, document, created_names):
        max_extent = 0.0
        if document is None:
            return max_extent
        for name in created_names or []:
            obj = document.getObject(name)
            if obj is None:
                continue
            shape = getattr(obj, "Shape", None)
            if shape is None or getattr(shape, "isNull", lambda: True)():
                continue
            try:
                bbox = shape.BoundBox
                max_extent = max(
                    max_extent,
                    float(bbox.XLength),
                    float(bbox.YLength),
                    float(bbox.ZLength),
                )
            except Exception:
                continue
        return max_extent

    def _repair_active_view_camera(self, document_name, created_names, active_view=None):
        if not FreeCAD.GuiUp:
            return
        document = FreeCAD.getDocument(document_name)
        if document is None:
            return
        max_extent = self._created_objects_max_extent(document, created_names)
        if max_extent <= 0.0:
            return
        if active_view is None:
            try:
                active_view = FreeCADGui.activeView()
            except Exception:
                active_view = None
        if active_view is None:
            return

        # The generated parts are small and centered near the origin. Some
        # focus/view-selection paths leave the orthographic camera with a tiny
        # height and overly tight clipping planes, which makes the viewport look
        # empty even though the object exists. Reset both scale and clip range.
        scale = max(50.0, max_extent * 6.0)
        try:
            if hasattr(active_view, "viewDefaultOrientation"):
                active_view.viewDefaultOrientation("Isometric", scale)
        except Exception:
            try:
                active_view.viewIsometric()
            except Exception:
                pass

        try:
            camera_text = active_view.getCamera() if hasattr(active_view, "getCamera") else ""
        except Exception:
            camera_text = ""
        if camera_text:
            near_distance = max(0.1, scale * 0.01)
            far_distance = max(scale * 20.0, near_distance + max_extent * 20.0)
            camera_text = _replace_camera_scalar(camera_text, "nearDistance", near_distance)
            camera_text = _replace_camera_scalar(camera_text, "farDistance", far_distance)
            camera_text = _replace_camera_scalar(camera_text, "focalDistance", scale)
            if "OrthographicCamera" in camera_text:
                camera_text = _replace_camera_scalar(camera_text, "height", scale)
            try:
                active_view.setCamera(camera_text)
            except Exception:
                pass

        try:
            FreeCADGui.updateGui()
        except Exception:
            pass
        self._log_debug(
            "focus_created_camera_repair",
            document=document_name,
            created_names=created_names,
            max_extent=max_extent,
            scale=scale,
        )

    def _focus_created_objects(self, document, tool_result):
        if document is None or not FreeCAD.GuiUp:
            return
        created_names = []
        seen = set()
        for name in self._iter_created_object_names(tool_result):
            if name in seen:
                continue
            seen.add(name)
            created_names.append(name)
        if not created_names:
            return

        # Determine which object is the final result — only that one should be
        # made visible and focused. Intermediate helpers (profiles, extrusion
        # bodies) are intentionally hidden by the ToolRegistry.
        result_object_name = ""
        if isinstance(tool_result, dict):
            result_object_name = tool_result.get("result_object", "")
            if not result_object_name:
                for sub in tool_result.get("results", []):
                    r = sub.get("result", {}) if isinstance(sub, dict) else {}
                    result_object_name = r.get("result_object", "")
                    if result_object_name:
                        break
        if not result_object_name:
            result_object_name = created_names[-1] if created_names else ""

        objects = []
        for name in created_names:
            obj = document.getObject(name)
            if obj is None:
                continue
            objects.append(obj)
            shape = getattr(obj, "Shape", None)
            bbox_payload = {}
            if shape is not None and not getattr(shape, "isNull", lambda: True)():
                try:
                    bbox = shape.BoundBox
                    bbox_payload = {
                        "xmin": float(bbox.XMin),
                        "ymin": float(bbox.YMin),
                        "zmin": float(bbox.ZMin),
                        "xmax": float(bbox.XMax),
                        "ymax": float(bbox.YMax),
                        "zmax": float(bbox.ZMax),
                        "xlen": float(bbox.XLength),
                        "ylen": float(bbox.YLength),
                        "zlen": float(bbox.ZLength),
                    }
                except Exception:
                    bbox_payload = {}
            view = getattr(obj, "ViewObject", None)
            # Only force visibility on the result object; leave intermediates
            # hidden as the ToolRegistry set them.
            is_result = (obj.Name == result_object_name)
            if view is not None and is_result:
                try:
                    view.Visibility = True
                except Exception:
                    pass
                try:
                    if hasattr(view, "DisplayMode"):
                        mode_names = []
                        if hasattr(view, "listDisplayModes"):
                            mode_names = list(view.listDisplayModes())
                        preferred = "Shaded" if "Shaded" in mode_names else ("Flat Lines" if "Flat Lines" in mode_names else "")
                        if preferred:
                            view.DisplayMode = preferred
                except Exception:
                    pass
                try:
                    if hasattr(view, "ShapeColor"):
                        view.ShapeColor = (0.84, 0.32, 0.18)
                except Exception:
                    pass
                try:
                    if hasattr(view, "LineColor"):
                        view.LineColor = (0.95, 0.95, 0.98)
                except Exception:
                    pass
                try:
                    if hasattr(view, "LineWidth"):
                        view.LineWidth = 3.0
                except Exception:
                    pass
                try:
                    if hasattr(view, "Transparency"):
                        view.Transparency = 0
                except Exception:
                    pass
            self._log_debug(
                "focus_created_object",
                document=getattr(document, "Name", ""),
                object_name=getattr(obj, "Name", ""),
                type_id=getattr(obj, "TypeId", ""),
                label=getattr(obj, "Label", ""),
                view_visible=getattr(view, "Visibility", None) if view is not None else None,
                view_display_mode=getattr(view, "DisplayMode", "") if view is not None else "",
                view_transparency=getattr(view, "Transparency", None) if view is not None else None,
                bbox=bbox_payload,
            )

        if not objects:
            return

        # Defer selection/focus until the GUI has had time to register the new
        # view provider. A single next-tick focus is not reliable enough here:
        # the object exists in the document, but the 3D scene can still lag one
        # or two event cycles behind.
        doc_name = document.Name
        focus_names = [result_object_name] if result_object_name else list(created_names)
        retry_delays_ms = (0, 150, 500)
        for attempt, delay_ms in enumerate(retry_delays_ms):
            QtCore.QTimer.singleShot(
                delay_ms,
                lambda doc_name=doc_name, focus_names=list(focus_names), attempt=attempt: self._deferred_focus(
                    doc_name,
                    focus_names,
                    attempt,
                    final_attempt=(attempt == len(retry_delays_ms) - 1),
                ),
            )

    def _deferred_focus(self, document_name, created_names, attempt=0, final_attempt=False):
        """Focus created objects after the event loop has processed pending updates."""
        try:
            document = FreeCAD.getDocument(document_name)
            if document is None:
                return
            if attempt == 0:
                # Recompute once before the first focus pass so the later retries
                # only pay the GUI-sync cost.
                document.recompute()
            FreeCADGui.updateGui()
            FreeCADGui.Selection.clearSelection(document_name)
            for name in created_names:
                obj = document.getObject(name)
                if obj is not None:
                    FreeCADGui.Selection.addSelection(document_name, name)
            self._apply_document_focus(document_name, created_names)
            # Explicitly fit the view
            try:
                gui_doc = FreeCADGui.getDocument(document_name)
                active_view = getattr(gui_doc, "ActiveView", None)
                if active_view is not None:
                    active_view.fitAll()
                else:
                    FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
            try:
                FreeCADGui.updateGui()
            except Exception:
                pass
        except Exception:
            pass
        try:
            selection_names = [obj.Name for obj in FreeCADGui.Selection.getSelection(document_name)]
        except Exception:
            selection_names = []
        self._log_debug(
            "focus_created_objects_attempt",
            document=document_name,
            created_names=created_names,
            selection=selection_names,
            attempt=attempt,
            final_attempt=bool(final_attempt),
        )
        if final_attempt:
            self._log_debug(
                "focus_created_objects_complete",
                document=document_name,
                created_names=created_names,
                selection=selection_names,
            )

    def _apply_document_focus(self, document_name, created_names):
        if not document_name or not FreeCAD.GuiUp:
            return
        document = FreeCAD.getDocument(document_name)
        if document is None:
            return
        objects = []
        for name in created_names or []:
            obj = document.getObject(name)
            if obj is not None:
                objects.append(obj)
        if not objects:
            return

        try:
            FreeCAD.setActiveDocument(document_name)
        except Exception:
            pass
        try:
            if hasattr(FreeCADGui, "setActiveDocument"):
                FreeCADGui.setActiveDocument(document_name)
        except Exception:
            pass

        gui_doc = None
        try:
            gui_doc = FreeCADGui.getDocument(document_name)
        except Exception:
            gui_doc = None
        if gui_doc is None:
            try:
                gui_doc = FreeCADGui.activeDocument()
            except Exception:
                gui_doc = None

        try:
            FreeCADGui.Selection.clearSelection(document_name)
            for obj in objects:
                FreeCADGui.Selection.addSelection(document_name, obj.Name)
        except Exception:
            pass

        active_view = None
        if gui_doc is not None:
            active_view = getattr(gui_doc, "ActiveView", None)
            if active_view is None:
                try:
                    active_view = gui_doc.activeView()
                except Exception:
                    active_view = None
        if active_view is None:
            try:
                active_view = FreeCADGui.activeView()
            except Exception:
                active_view = None

        if active_view is not None:
            try:
                active_view.viewIsometric()
            except Exception:
                try:
                    active_view.viewAxonometric()
                except Exception:
                    pass

        try:
            FreeCADGui.SendMsgToActiveView("ViewSelection")
        except Exception:
            pass
        try:
            FreeCADGui.updateGui()
        except Exception:
            pass
        view_type = type(active_view).__name__ if active_view is not None else ""
        try:
            selection_names = [obj.Name for obj in FreeCADGui.Selection.getSelection(document_name)]
        except Exception:
            selection_names = []
        self._log_debug(
            "focus_created_view_state",
            document=document_name,
            view_type=view_type,
            selection=selection_names,
            created_names=created_names,
            active_gui_document=getattr(getattr(gui_doc, "Document", None), "Name", "") if gui_doc is not None else "",
        )

    def _execute_tool_request_on_gui_thread(self, event, run_id):
        request_id = event.get("request_id", "")
        try:
            document = FreeCAD.ActiveDocument
            if not document:
                self._bridge.submit_tool_results(
                    run_id,
                    {"request_id": request_id, "result": {"ok": False, "error": "No active document"}},
                )
                return
            self._auto_validation_hold_until = time.time() + 4.0
            self._log_debug(
                "gui_tool_request_start",
                run_id=run_id,
                request_id=request_id,
                tool_name=event.get("tool_name", ""),
                document=getattr(document, "Name", ""),
            )
            result = ToolRegistry.execute_tool_request(event, document=document)
            self._bridge.submit_tool_results(
                run_id,
                {"request_id": request_id, "result": result},
            )
            if self._run_is_interactive(run_id):
                self._widget.append_transcript(self._format_tool_result_text(event, result))
            if result.get("ok", False):
                self._focus_created_objects(document, result)
            elif self._run_is_interactive(run_id):
                self._widget.append_transcript("Local tool request failed: {0}".format(result.get("error", "")))
            self._log_debug(
                "gui_tool_request_complete",
                run_id=run_id,
                request_id=request_id,
                ok=bool(result.get("ok", False)),
                error=result.get("error", ""),
            )
        except Exception as exc:
            self._log_debug(
                "gui_tool_request_exception",
                run_id=run_id,
                request_id=request_id,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            result = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
            try:
                self._bridge.submit_tool_results(
                    run_id,
                    {"request_id": request_id, "result": result},
                )
            except Exception:
                pass
            if self._run_is_interactive(run_id):
                self._widget.append_transcript("Local tool request crashed: {0}".format(str(exc)))

    def ensure_initialized(self):
        if self._initialized:
            return
        self._observers.start()
        self._initialized = True

    def show_panel(self):
        self.ensure_initialized()
        if self._dock is None:
            self._create_panel()
        self._sync_model_from_document()
        self._dock.show()
        self._dock.raise_()
        self._dock.setVisible(True)
        return self._dock

    def on_document_event(self, reason, document):
        if reason in ("activate", "created_document"):
            # Reset user selection flag when switching to a different document
            # so it syncs from the new document's session
            if document and document.Name != self._last_document_name:
                self._user_selected_model = False
            self._sync_model_from_document(document)
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
            # Reset user selection when document is closed
            self._user_selected_model = False
            if self._widget is not None:
                self._widget.set_issues([])
                self._widget.set_report(None)
                self._widget.set_status("MagicCAD AI idle")

    def validate_document(self, document=None, selection_only=False, intent="validate", prompt=None, auto=False):
        document = document or FreeCAD.ActiveDocument
        if document is None:
            if intent == "copilot" and not auto:
                document = self._ensure_copilot_document()
            if document is None:
                self._set_status("No active document to validate")
                return
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
        selected_model = self._widget.current_model()
        stored_model = getattr(session, "ModelName", "") if session is not None else ""
        stored_previous_response_id = getattr(session, "PreviousResponseId", "") if session is not None else ""
        previous_response_id = ""
        if self._provider_for_model(selected_model) == "openai" and self._provider_for_model(stored_model or selected_model) == "openai":
            previous_response_id = stored_previous_response_id

        request = {
            "thread_id": getattr(session, "ThreadId", ""),
            "previous_response_id": previous_response_id,
            "snapshot": snapshot,
            "intent": intent,
            "prompt": prompt,
            "model": selected_model,
            "selection_only": selection_only,
            "requested_at": _utc_now(),
        }
        response = self._bridge.start_run(request)
        if response is None:
            self._set_status("Failed to start MagicCAD AI run")
            return

        self._running_run_id = response.get("run_id", "")
        self._pending_approval = None
        self._run_meta[self._running_run_id] = {"intent": intent, "auto": auto}
        SessionObjects.update_session(
            session,
            thread_id=response.get("thread_id", ""),
            run_id=response.get("run_id", ""),
            model=request["model"],
            status="running",
            snapshot_hash=snapshot.get("snapshot_hash", ""),
            payload={"intent": intent, "selection_only": selection_only, "auto": auto},
        )
        self._widget.set_draft_state(False, False, False)
        self._sync_model_from_document(document)
        self._set_status("MagicCAD AI run in progress...")

    def run_copilot(self):
        prompt = self._widget.current_prompt().strip()
        if not prompt:
            return
        self._widget.append_user_transcript(prompt)
        self._widget.prompt_input.clear()
        self.validate_document(selection_only=False, intent="copilot", prompt=prompt, auto=False)

    def _ensure_copilot_document(self):
        document = FreeCAD.ActiveDocument
        if document is not None:
            return document
        try:
            document = FreeCAD.newDocument("MagicCAD")
        except Exception as exc:
            self._set_status("Failed to create a new document: {0}".format(exc))
            return None
        if document is not None:
            self._set_status("Created a new document for the copilot run")
        return document

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
        self._widget.run_copilot_button.clicked.connect(self.run_copilot)
        self._widget.highlight_issue_button.clicked.connect(self.highlight_current_issue)
        self._widget.clear_highlight_button.clicked.connect(self.clear_highlight)
        self._widget.apply_button.clicked.connect(self.apply_pending_draft)
        self._widget.revise_button.clicked.connect(self.revise_pending_draft)
        self._widget.reject_button.clicked.connect(self.reject_pending_draft)
        self._widget.export_button.clicked.connect(self.export_report)
        self._widget.tabs.currentChanged.connect(self._on_tab_changed)
        self._widget.issue_list.currentRowChanged.connect(lambda _row: self._widget.show_issue_details(self._widget.current_issue()))
        self._widget.issue_list.itemDoubleClicked.connect(lambda _item: self.highlight_current_issue())
        self._widget.set_draft_state(False, False, False)

        self._dock = QtWidgets.QDockWidget("MagicCAD AI")
        self._dock.setObjectName("MagicCADAIDock")
        self._dock.setWidget(self._widget)
        self._dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        FreeCADGui.getMainWindow().addDockWidget(Qt.RightDockWidgetArea, self._dock)
        self._sync_model_from_document()

    def _run_is_interactive(self, run_id):
        meta = self._run_meta.get(run_id, {})
        return bool(meta) and not meta.get("auto", False)

    def _on_bridge_status(self, status):
        self._set_status(status)

    def _on_bridge_error(self, context, message):
        self._widget.append_transcript("Bridge error [{0}]: {1}".format(context, message))
        self._set_status("MagicCAD AI bridge error")

    def _on_tab_changed(self, index):
        if self._widget is None or index != 2:
            return
        report = self._last_report
        if not report:
            document = FreeCAD.ActiveDocument
            if document is not None:
                _root, _session, report_obj = SessionObjects.ensure_storage(document)
                report = SessionObjects.report_payload(report_obj)
                if report:
                    self._last_report = report
        self._widget.set_report(report)

    def _on_bridge_event(self, event):
        event_name = event.get("event", "")
        run_id = event.get("run_id", "")
        document = FreeCAD.ActiveDocument
        _root = session = report_obj = None
        if document is not None:
            _root, session, report_obj = SessionObjects.ensure_storage(document)

        if event_name == "run_started":
            self._running_run_id = run_id
            self._handled_tool_request_ids.clear()
            if session is not None:
                SessionObjects.update_session(session, run_id=run_id, status="running")
        elif event_name == "node_status":
            self._set_status("{0}: {1}".format(event.get("node", "node"), event.get("status", "")))
        elif event_name == "backend_warning":
            if self._run_is_interactive(run_id):
                self._widget.append_transcript(event.get("message", "Backend warning"))
            self._set_status(event.get("message", "Backend warning"))
        elif event_name == "assistant_delta":
            if self._run_is_interactive(run_id):
                self._widget.append_transcript(event.get("text", ""), markdown=True)
        elif event_name == "issues_delta":
            issues = event.get("issues", [])
            self._widget.set_issues(issues)
            self._widget.show_issue_details(self._widget.current_issue())
            if self._run_is_interactive(run_id):
                self._widget.tabs.setCurrentIndex(1 if issues else 0)
        elif event_name == "approval_required":
            self._pending_approval = event
            self._widget.set_draft_state(True, True, True)
            proposed_changes = event.get("proposed_changes", []) or []
            summary_lines = ["# Approval Required", "", event.get("message", "Approval is required before applying the proposed change."), ""]
            if proposed_changes:
                summary_lines.append("## Proposed Changes")
                for change in proposed_changes:
                    summary_lines.append("- {0}".format(change.get("summary", "")))
            self._widget.set_report({"markdown": "\n".join(summary_lines)})
            self._widget.set_approval_notice("Local document changes need approval. Review the draft below, then use Apply Draft, Revise Draft, or Reject Draft.")
            self._widget.tabs.setCurrentIndex(2)
        elif event_name == "tool_request":
            request_id = event.get("request_id", "")
            if request_id and request_id in self._handled_tool_request_ids:
                return
            if request_id:
                self._handled_tool_request_ids.add(request_id)
            if self._run_is_interactive(run_id):
                self._widget.append_transcript(self._format_tool_request_text(event))
            self.toolRequestQueued.emit(dict(event), str(run_id or ""))
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
            if self._widget.tabs.currentIndex() == 2:
                self._widget.set_report(report)
            self._widget.set_approval_notice("")
            has_pending = bool(self._pending_approval)
            self._widget.set_draft_state(has_pending, has_pending, has_pending)
        elif event_name == "run_error":
            if self._run_is_interactive(run_id):
                self._widget.append_transcript("Run error: {0}".format(event.get("message", "")))
            if session is not None:
                SessionObjects.update_session(session, status="error")
        elif event_name == "run_finished":
            self._running_run_id = ""
            # Do NOT clear _handled_tool_request_ids here — tool_request events
            # can arrive after run_finished due to graph resume re-emitting them.
            # The set is cleared on the next run_started instead.
            finished_status = event.get("status", "completed")
            self._set_status("Run {0} finished with status {1}".format(run_id, finished_status))
            self._run_meta.pop(run_id, None)
            if session is not None:
                SessionObjects.update_session(session, status=finished_status)
            if finished_status != "awaiting_approval":
                self._pending_approval = None
                self._widget.set_approval_notice("")
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
