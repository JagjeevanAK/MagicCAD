# SPDX-License-Identifier: LGPL-2.1-or-later

import argparse
import datetime
import html as html_lib
import json
import os
import queue
import re
import sqlite3
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import Validators


DEFAULT_MODEL = "gpt-5.4"
RULEPACK_VERSION = "v1"


def utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class SQLiteRunStore:
    def __init__(self, path):
        self._path = path
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            """
            create table if not exists runs (
                run_id text primary key,
                thread_id text not null,
                status text not null,
                state_json text not null,
                report_json text,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        self._db.commit()

    def save_run(self, run):
        with self._lock:
            self._db.execute(
                """
                insert into runs(run_id, thread_id, status, state_json, report_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                    thread_id=excluded.thread_id,
                    status=excluded.status,
                    state_json=excluded.state_json,
                    report_json=excluded.report_json,
                    updated_at=excluded.updated_at
                """,
                (
                    run.run_id,
                    run.thread_id,
                    run.status,
                    json.dumps(run.state, sort_keys=True),
                    json.dumps(run.state.get("report", {}), sort_keys=True),
                    run.created_at,
                    run.updated_at,
                ),
            )
            self._db.commit()


class RunRecord:
    def __init__(self, request):
        self.run_id = uuid.uuid4().hex
        self.thread_id = request.get("thread_id") or uuid.uuid4().hex
        self.status = "queued"
        self.created_at = utc_now()
        self.updated_at = self.created_at
        self.request = request
        self.state = {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "model": request.get("model", DEFAULT_MODEL),
            "intent": request.get("intent", "validate"),
            "prompt": request.get("prompt", ""),
            "selection_only": bool(request.get("selection_only", False)),
            "snapshot": request.get("snapshot", {}),
            "issues": [],
            "assistant_text": "",
            "proposed_changes": [],
            "tool_results": [],
            "report": {},
            "approval_status": "not_required",
        }
        self.events = []
        self.condition = threading.Condition()
        self.terminal = False
        self.approval_event = threading.Event()
        self.tool_result_event = threading.Event()
        self.pending_decision = None
        self.pending_decision_payload = {}
        self.pending_tool_result = None

    def publish(self, event_name, **payload):
        event = {
            "event": event_name,
            "run_id": self.run_id,
            "thread_id": self.thread_id,
        }
        event.update(payload)
        with self.condition:
            self.events.append(event)
            self.updated_at = utc_now()
            self.condition.notify_all()
        return event

    def close(self, status):
        with self.condition:
            self.status = status
            self.updated_at = utc_now()
            self.terminal = True
            self.condition.notify_all()


class PromptInterpreter:
    GEAR_HINTS = ("gear", "spur gear", "involute")

    @classmethod
    def plan_changes(cls, snapshot, prompt, issues):
        prompt = (prompt or "").strip()
        if not prompt:
            return []
        lowered = prompt.lower()
        if any(token in lowered for token in cls.GEAR_HINTS):
            return [cls._gear_change(prompt, snapshot)]
        return []

    @classmethod
    def revise_changes(cls, proposed_changes, feedback):
        if not proposed_changes:
            return proposed_changes
        feedback = (feedback or "").strip()
        if not feedback:
            return proposed_changes
        revised = json.loads(json.dumps(proposed_changes))
        op = revised[0].get("ops", [{}])[0]
        teeth = cls._extract_number(feedback, r"(\d+)\s*teeth?", int(op.get("number_of_teeth", 10)))
        module = cls._extract_number(feedback, r"module\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)", float(op.get("module", 2.0)))
        pressure_angle = cls._extract_number(
            feedback,
            r"pressure angle\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)",
            float(op.get("pressure_angle", 20.0)),
        )
        thickness = cls._extract_number(
            feedback,
            r"(?:thickness|height)\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)",
            float(op.get("thickness", 8.0)),
        )
        bore = cls._extract_number(
            feedback,
            r"(?:bore|hole|center bore)\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)",
            float(op.get("center_bore", 6.0)),
        )
        op.update(
            {
                "number_of_teeth": int(teeth),
                "module": float(module),
                "pressure_angle": float(pressure_angle),
                "thickness": float(thickness),
                "center_bore": float(bore),
            }
        )
        revised[0]["summary"] = cls._gear_summary(op)
        return revised

    @classmethod
    def _gear_change(cls, prompt, snapshot):
        op = {
            "op": "create_involute_gear",
            "name": cls._pick_result_name(snapshot),
            "number_of_teeth": int(cls._extract_number(prompt, r"(\d+)\s*teeth?", 10)),
            "module": float(cls._extract_number(prompt, r"module\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)", 2.0)),
            "pressure_angle": float(
                cls._extract_number(prompt, r"pressure angle\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)", 20.0)
            ),
            "thickness": float(cls._extract_number(prompt, r"(?:thickness|height)\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)", 8.0)),
            "center_bore": float(
                cls._extract_number(prompt, r"(?:bore|hole|center bore)\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)", 6.0)
            ),
        }
        return {
            "change_id": uuid.uuid4().hex,
            "summary": cls._gear_summary(op),
            "risk_level": "medium",
            "ops": [op, {"op": "recompute"}],
        }

    @classmethod
    def _gear_summary(cls, op):
        return (
            "Create an involute gear named {0} with {1} teeth, module {2}, pressure angle {3} deg, thickness {4} mm, and center bore {5} mm."
        ).format(
            op.get("name", "InvoluteGear"),
            op.get("number_of_teeth", 10),
            op.get("module", 2.0),
            op.get("pressure_angle", 20.0),
            op.get("thickness", 8.0),
            op.get("center_bore", 6.0),
        )

    @classmethod
    def _pick_result_name(cls, snapshot):
        names = {obj.get("name", "") for obj in snapshot.get("objects", [])}
        candidate = "MagicGear"
        index = 1
        while candidate in names:
            index += 1
            candidate = "MagicGear{0:03d}".format(index)
        return candidate

    @classmethod
    def _extract_number(cls, text, pattern, default):
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return default
        try:
            return float(match.group(1))
        except Exception:
            return default


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

    def summarize(self, snapshot, issues, prompt, model):
        if not self.available:
            return ""
        payload = {
            "prompt": prompt,
            "issue_count": len(issues),
            "issues": issues[:10],
            "objects": snapshot.get("objects", [])[:20],
            "selection_only": snapshot.get("selection", []),
        }
        system_prompt = (
            "You are MagicCAD AI. Provide concise, actionable CAD review feedback for a FreeCAD-based desktop tool. "
            "If a change request is present, describe the expected draft in plain language and mention important risks."
        )
        try:
            response = self._client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload)}]},
                ],
            )
            text = getattr(response, "output_text", "")
            if text:
                return text.strip()
            for item in getattr(response, "output", []):
                for content in getattr(item, "content", []):
                    if getattr(content, "type", "") == "output_text":
                        return getattr(content, "text", "").strip()
        except Exception as exc:
            self._error = str(exc)
        return ""


class LangGraphAdapter:
    def __init__(self, engine):
        self._engine = engine
        self.available = False
        self._compiled = None
        try:
            from langgraph.graph import END, StateGraph
        except Exception:
            return
        try:
            graph = StateGraph(dict)
            graph.add_node("intake", self._wrap("intake", engine.intake))
            graph.add_node("normalize_snapshot", self._wrap("normalize_snapshot", engine.normalize_snapshot))
            graph.add_node("deterministic_validate", self._wrap("deterministic_validate", engine.deterministic_validate))
            graph.add_node("llm_explain", self._wrap("llm_explain", engine.llm_explain))
            graph.add_node("draft_plan", self._wrap("draft_plan", engine.draft_plan))
            graph.add_node("report_render", self._wrap("report_render", engine.report_render))
            graph.set_entry_point("intake")
            graph.add_edge("intake", "normalize_snapshot")
            graph.add_edge("normalize_snapshot", "deterministic_validate")
            graph.add_edge("deterministic_validate", "llm_explain")
            graph.add_edge("llm_explain", "draft_plan")
            graph.add_edge("draft_plan", "report_render")
            graph.add_edge("report_render", END)
            self._compiled = graph.compile()
            self.available = True
        except Exception:
            self._compiled = None
            self.available = False

    def run(self, state):
        if not self.available or self._compiled is None:
            return state
        return self._compiled.invoke(state)

    def _wrap(self, node_name, fn):
        def wrapper(state):
            self._engine.publish_node(node_name, "running")
            updates = fn(state)
            self._engine.publish_node(node_name, "completed")
            return updates

        return wrapper


class MagicCADAgentEngine:
    def __init__(self, store):
        self._store = store
        self._llm = OpenAIResponder()
        self._local = threading.local()
        self._langgraph = LangGraphAdapter(self)

    def process_run(self, run):
        self._local.run = run
        try:
            run.status = "running"
            self._persist(run)
            self._publish(run, "run_started", status="running")
            state = self._execute_pipeline(run)
            run.state.update(state)
            if run.state.get("proposed_changes"):
                run.state = self._approval_loop(run, run.state)
            run.state["report"] = self._render_report(run.state)
            self._persist(run)
            self._publish(run, "report_ready", report=run.state["report"])
            run.status = "completed"
            self._persist(run)
            self._publish(run, "run_finished", status="completed")
            run.close("completed")
            self._persist(run)
        except Exception as exc:
            run.status = "error"
            run.state["error"] = str(exc)
            self._persist(run)
            self._publish(run, "run_error", message=str(exc), traceback=traceback.format_exc())
            self._publish(run, "run_finished", status="error")
            run.close("error")
            self._persist(run)
        finally:
            self._local.run = None

    def publish_node(self, node_name, status):
        run = getattr(self._local, "run", None)
        if run is not None:
            self._publish(run, "node_status", node=node_name, status=status)

    def intake(self, state):
        summary = "Intake complete for {0} objects.".format(len(state.get("snapshot", {}).get("objects", [])))
        return {"phase": "intake", "summary": summary}

    def normalize_snapshot(self, state):
        snapshot = state.get("snapshot", {})
        normalized = dict(snapshot)
        normalized.setdefault("objects", [])
        normalized.setdefault("selection", [])
        normalized.setdefault("dependency_edges", [])
        normalized.setdefault("recompute_errors", [])
        return {"phase": "normalize_snapshot", "snapshot": normalized}

    def deterministic_validate(self, state):
        issues = Validators.validate_snapshot(state.get("snapshot", {}))
        run = getattr(self._local, "run", None)
        if run is not None:
            self._publish(run, "issues_delta", issues=issues)
        return {
            "phase": "deterministic_validate",
            "issues": issues,
            "issue_counts": Validators.issue_counts(issues),
        }

    def llm_explain(self, state):
        snapshot = state.get("snapshot", {})
        issues = state.get("issues", [])
        prompt = state.get("prompt", "")
        model = state.get("model", DEFAULT_MODEL)
        explanation = self._llm.summarize(snapshot, issues, prompt, model)
        if not explanation:
            explanation = self._fallback_explanation(snapshot, issues, prompt)
        run = getattr(self._local, "run", None)
        if run is not None:
            self._publish(run, "assistant_delta", text=explanation)
        return {
            "phase": "llm_explain",
            "assistant_text": explanation,
            "backend": {
                "openai": self._llm.available,
                "langgraph": self._langgraph.available,
                "model": model,
            },
        }

    def draft_plan(self, state):
        changes = PromptInterpreter.plan_changes(
            state.get("snapshot", {}),
            state.get("prompt", ""),
            state.get("issues", []),
        )
        return {
            "phase": "draft_plan",
            "proposed_changes": changes,
            "approval_status": "required" if changes else "not_required",
        }

    def report_render(self, state):
        return {
            "phase": "report_render",
            "report": self._render_report(state),
        }

    def _execute_pipeline(self, run):
        state = dict(run.state)
        if self._langgraph.available:
            result = self._langgraph.run(state)
            return result if isinstance(result, dict) else state

        for node_name, fn in (
            ("intake", self.intake),
            ("normalize_snapshot", self.normalize_snapshot),
            ("deterministic_validate", self.deterministic_validate),
            ("llm_explain", self.llm_explain),
            ("draft_plan", self.draft_plan),
            ("report_render", self.report_render),
        ):
            self.publish_node(node_name, "running")
            state.update(fn(state))
            self.publish_node(node_name, "completed")
        return state

    def _approval_loop(self, run, state):
        proposed_changes = state.get("proposed_changes", [])
        while proposed_changes:
            run.status = "awaiting_approval"
            self._persist(run)
            run.approval_event.clear()
            self._publish(
                run,
                "approval_required",
                proposed_changes=proposed_changes,
                message="Approval is required before MagicCAD AI applies local document changes.",
            )
            run.approval_event.wait()
            decision = run.pending_decision or "reject"
            payload = run.pending_decision_payload or {}
            run.pending_decision = None
            run.pending_decision_payload = {}
            run.status = "running"
            self._persist(run)

            if decision == "reject":
                state["approval_status"] = "rejected"
                return state
            if decision == "edit":
                proposed_changes = PromptInterpreter.revise_changes(proposed_changes, payload.get("feedback", ""))
                state["proposed_changes"] = proposed_changes
                state["approval_status"] = "edited"
                self._publish(run, "assistant_delta", text="Revised the proposed draft based on the edit feedback.")
                continue

            change_id = payload.get("change_id", "")
            selected = self._select_change(proposed_changes, change_id)
            request_id = uuid.uuid4().hex
            tool_request = {
                "request_id": request_id,
                "tool_name": "apply_ops",
                "arguments": {"ops": selected.get("ops", [])},
            }
            run.tool_result_event.clear()
            self._publish(run, "tool_request", **tool_request)
            run.tool_result_event.wait()
            tool_result = run.pending_tool_result or {"result": {"ok": False, "error": "No tool result received"}}
            run.pending_tool_result = None
            state.setdefault("tool_results", []).append(tool_result)
            state["approval_status"] = "approved" if tool_result.get("result", {}).get("ok") else "failed"
            state["applied_change"] = selected
            if tool_result.get("result", {}).get("ok"):
                self._publish(run, "assistant_delta", text="Approved change applied locally and recomputed.")
            else:
                self._publish(
                    run,
                    "assistant_delta",
                    text="Approved change failed locally: {0}".format(tool_result.get("result", {}).get("error", "unknown error")),
                )
            return state
        return state

    def _select_change(self, proposed_changes, change_id):
        if not change_id:
            return proposed_changes[0]
        for change in proposed_changes:
            if change.get("change_id") == change_id:
                return change
        return proposed_changes[0]

    def _fallback_explanation(self, snapshot, issues, prompt):
        object_count = len(snapshot.get("objects", []))
        counts = Validators.issue_counts(issues)
        summary = "Reviewed {0} objects and found {1} issues.".format(object_count, counts.get("total", 0))
        if prompt:
            summary += " Request: {0}".format(prompt.strip())
        if issues:
            top_issue = issues[0]
            summary += " Highest priority: {0}".format(top_issue.get("message", ""))
        else:
            summary += " No deterministic validation risks were detected."
        return summary

    def _render_report(self, state):
        issues = state.get("issues", [])
        proposed_changes = state.get("proposed_changes", [])
        counts = Validators.issue_counts(issues)
        summary = state.get("assistant_text") or self._fallback_explanation(state.get("snapshot", {}), issues, state.get("prompt", ""))
        markdown_lines = [
            "# MagicCAD AI Validation Report",
            "",
            "Summary: {0}".format(summary),
            "",
            "Issue counts: {0}".format(json.dumps(counts, sort_keys=True)),
            "",
        ]
        if issues:
            markdown_lines.append("## Issues")
            for issue in issues:
                markdown_lines.append(
                    "- [{0}] {1} Fix: {2}".format(
                        issue.get("severity", "low").upper(),
                        issue.get("message", ""),
                        issue.get("recommended_fix", ""),
                    )
                )
            markdown_lines.append("")
        else:
            markdown_lines.extend(["## Issues", "- No deterministic issues detected.", ""])

        if proposed_changes:
            markdown_lines.append("## Proposed Changes")
            for change in proposed_changes:
                markdown_lines.append("- {0}".format(change.get("summary", "")))
            markdown_lines.append("")

        tool_results = state.get("tool_results", [])
        if tool_results:
            markdown_lines.append("## Tool Results")
            for result in tool_results:
                ok = result.get("result", {}).get("ok", False)
                markdown_lines.append("- {0}".format("Applied successfully" if ok else result.get("result", {}).get("error", "Failed")))
            markdown_lines.append("")

        markdown = "\n".join(markdown_lines).strip() + "\n"
        html = "<html><body><pre>{0}</pre></body></html>".format(html_lib.escape(markdown))
        return {
            "report_id": uuid.uuid4().hex,
            "thread_id": state.get("thread_id", ""),
            "snapshot_hash": state.get("snapshot", {}).get("snapshot_hash", ""),
            "summary": summary,
            "issue_counts": counts,
            "issues": issues,
            "proposed_changes": proposed_changes,
            "model_info": {
                "requested_model": state.get("model", DEFAULT_MODEL),
                "openai_enabled": self._llm.available,
                "langgraph_enabled": self._langgraph.available,
            },
            "rulepack_version": RULEPACK_VERSION,
            "created_at": utc_now(),
            "markdown": markdown,
            "html": html,
        }

    def _publish(self, run, event_name, **payload):
        run.publish(event_name, **payload)
        self._persist(run)

    def _persist(self, run):
        self._store.save_run(run)


class ServerState:
    def __init__(self, database_path):
        self._store = SQLiteRunStore(database_path)
        self._engine = MagicCADAgentEngine(self._store)
        self._runs = {}
        self._lock = threading.Lock()

    def health(self):
        return {"ok": True, "status": "ready", "timestamp": utc_now()}

    def create_run(self, request):
        run = RunRecord(request)
        with self._lock:
            self._runs[run.run_id] = run
        self._store.save_run(run)
        worker = threading.Thread(target=self._engine.process_run, args=(run,), daemon=True)
        worker.start()
        return run

    def get_run(self, run_id):
        with self._lock:
            return self._runs.get(run_id)

    def resume_run(self, run_id, decision, payload):
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run.pending_decision = decision
        run.pending_decision_payload = payload or {}
        run.approval_event.set()
        self._store.save_run(run)
        return {"ok": True, "run_id": run_id, "status": run.status}

    def submit_tool_results(self, run_id, payload):
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run.pending_tool_result = payload or {}
        run.tool_result_event.set()
        self._store.save_run(run)
        return {"ok": True, "run_id": run_id}


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "MagicCADAI/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, self.server.state.health())
            return

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 4 and parts[0] == "v1" and parts[1] == "runs" and parts[3] == "events":
            run = self.server.state.get_run(parts[2])
            if run is None:
                self._send_json(404, {"ok": False, "error": "Run not found"})
                return
            self._stream_events(run)
            return

        self._send_json(404, {"ok": False, "error": "Unknown endpoint"})

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/v1/runs":
            request = self._read_json_body()
            run = self.server.state.create_run(request)
            self._send_json(200, {"ok": True, "run_id": run.run_id, "thread_id": run.thread_id})
            return

        if len(parts) == 4 and parts[0] == "v1" and parts[1] == "runs" and parts[3] == "resume":
            body = self._read_json_body()
            try:
                response = self.server.state.resume_run(parts[2], body.get("decision", "reject"), body.get("payload", {}))
            except KeyError:
                self._send_json(404, {"ok": False, "error": "Run not found"})
                return
            self._send_json(200, response)
            return

        if len(parts) == 4 and parts[0] == "v1" and parts[1] == "runs" and parts[3] == "tool-results":
            body = self._read_json_body()
            try:
                response = self.server.state.submit_tool_results(parts[2], body)
            except KeyError:
                self._send_json(404, {"ok": False, "error": "Run not found"})
                return
            self._send_json(200, response)
            return

        self._send_json(404, {"ok": False, "error": "Unknown endpoint"})

    def log_message(self, format_string, *args):
        return

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8", "replace")
        if not body.strip():
            return {}
        return json.loads(body)

    def _send_json(self, status, payload):
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream_events(self, run):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        index = 0
        try:
            while True:
                with run.condition:
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
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = json.dumps(event, sort_keys=True)
                self.wfile.write("event: {0}\n".format(event.get("event", "message")).encode("utf-8"))
                self.wfile.write("data: {0}\n\n".format(payload).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="MagicCAD AI sidecar server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50173)
    parser.add_argument("--database", default=os.path.join(os.getcwd(), "magiccadai.sqlite3"))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    server.state = ServerState(args.database)
    print("MagicCADAI sidecar listening on http://{0}:{1}".format(args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
