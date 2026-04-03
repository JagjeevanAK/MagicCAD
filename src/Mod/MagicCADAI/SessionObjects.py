# SPDX-License-Identifier: LGPL-2.1-or-later

import datetime
import json

import FreeCAD


ROOT_NAME = "MagicCADAIData"
SESSION_NAME = "MagicCADAISession"
REPORT_NAME = "MagicCADAIReport"


def _utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _ensure_property(obj, type_name, name, group, doc, default=None):
    if name not in obj.PropertiesList:
        obj.addProperty(type_name, name, group, doc, locked=True)
        if default is not None:
            try:
                setattr(obj, name, default)
            except Exception:
                pass


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


class RootProxy(_BaseProxy):
    proxy_type = "MagicCADAI::Root"

    def ensure_properties(self, obj):
        _ensure_property(obj, "App::PropertyString", "Kind", "MagicCADAI", "Storage type", "Root")


class SessionProxy(_BaseProxy):
    proxy_type = "MagicCADAI::Session"

    def ensure_properties(self, obj):
        _ensure_property(obj, "App::PropertyString", "Kind", "MagicCADAI", "Storage type", "Session")
        _ensure_property(obj, "App::PropertyString", "ThreadId", "MagicCADAI", "LangGraph/OpenAI thread id", "")
        _ensure_property(obj, "App::PropertyString", "LastRunId", "MagicCADAI", "Last sidecar run id", "")
        _ensure_property(obj, "App::PropertyString", "ModelName", "MagicCADAI", "Selected model", "")
        _ensure_property(obj, "App::PropertyString", "LastStatus", "MagicCADAI", "Last run status", "")
        _ensure_property(obj, "App::PropertyString", "LastSnapshotHash", "MagicCADAI", "Last snapshot hash", "")
        _ensure_property(obj, "App::PropertyString", "PreviousResponseId", "MagicCADAI", "Last provider-specific conversation token", "")
        _ensure_property(obj, "App::PropertyString", "LastPhase", "MagicCADAI", "Last assistant phase", "")
        _ensure_property(obj, "App::PropertyString", "LastUpdatedUtc", "MagicCADAI", "Last update time", "")
        _ensure_property(obj, "App::PropertyString", "Payload", "MagicCADAI", "Serialized session data", "{}")


class ReportProxy(_BaseProxy):
    proxy_type = "MagicCADAI::ValidationReport"

    def ensure_properties(self, obj):
        _ensure_property(obj, "App::PropertyString", "Kind", "MagicCADAI", "Storage type", "Report")
        _ensure_property(obj, "App::PropertyString", "ReportId", "MagicCADAI", "Current report id", "")
        _ensure_property(obj, "App::PropertyString", "ThreadId", "MagicCADAI", "Conversation thread id", "")
        _ensure_property(obj, "App::PropertyString", "SnapshotHash", "MagicCADAI", "Snapshot hash", "")
        _ensure_property(obj, "App::PropertyString", "Summary", "MagicCADAI", "Report summary", "")
        _ensure_property(obj, "App::PropertyInteger", "IssueCount", "MagicCADAI", "Number of issues", 0)
        _ensure_property(obj, "App::PropertyString", "Markdown", "MagicCADAI", "Markdown report body", "")
        _ensure_property(obj, "App::PropertyString", "Html", "MagicCADAI", "HTML report body", "")
        _ensure_property(obj, "App::PropertyString", "Payload", "MagicCADAI", "Serialized report payload", "{}")


class _ViewProvider:
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


def _ensure_view_provider(obj):
    if not FreeCAD.GuiUp:
        return
    try:
        if getattr(obj.ViewObject, "Proxy", None) is None:
            _ViewProvider(obj.ViewObject)
    except Exception:
        pass


def _ensure_root(document):
    root = document.getObject(ROOT_NAME)
    if root is None:
        root = document.addObject("App::DocumentObjectGroupPython", ROOT_NAME)
        RootProxy(root)
        _ensure_view_provider(root)
    elif getattr(getattr(root, "Proxy", None), "Type", "") != RootProxy.proxy_type:
        RootProxy(root)
        _ensure_view_provider(root)
    return root


def _ensure_feature(document, name, proxy_class):
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


def ensure_storage(document=None):
    document = document or FreeCAD.ActiveDocument
    if document is None:
        return None, None, None

    root = _ensure_root(document)
    session = _ensure_feature(document, SESSION_NAME, SessionProxy)
    report = _ensure_feature(document, REPORT_NAME, ReportProxy)

    current = set(obj.Name for obj in root.Group)
    wanted = [session, report]
    for obj in wanted:
        if obj.Name not in current:
            root.addObject(obj)
    return root, session, report


def session_payload(session):
    try:
        return json.loads(session.Payload) if session and session.Payload else {}
    except Exception:
        return {}


def report_payload(report):
    try:
        return json.loads(report.Payload) if report and report.Payload else {}
    except Exception:
        return {}


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


def update_report(report, report_data):
    if report is None or not report_data:
        return
    report.ReportId = report_data.get("report_id", "")
    report.ThreadId = report_data.get("thread_id", "")
    report.SnapshotHash = report_data.get("snapshot_hash", "")
    report.Summary = report_data.get("summary", "")
    report.IssueCount = int(report_data.get("issue_counts", {}).get("total", len(report_data.get("issues", []))))
    report.Markdown = report_data.get("markdown", "")
    report.Html = report_data.get("html", "")
    report.Payload = json.dumps(report_data, sort_keys=True)
