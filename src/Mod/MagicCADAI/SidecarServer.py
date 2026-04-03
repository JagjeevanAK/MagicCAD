# SPDX-License-Identifier: LGPL-2.1-or-later

import argparse
import datetime
import html as html_lib
import json
import os
import re
import sqlite3
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import Validators


DEFAULT_MODEL = "gpt-5.4"
GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"
RULEPACK_VERSION = "v1"

# Model provider detection
def _get_model_provider(model_name):
    """Detect which provider to use based on model name."""
    if not model_name:
        return "openai"
    model_lower = model_name.lower()
    if model_lower.startswith("gemini"):
        return "gemini"
    return "openai"

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


def utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _json_dumps(value):
    return json.dumps(value, sort_keys=True)


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
                request_json text not null default '{}',
                state_json text not null,
                report_json text,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        self._ensure_column("request_json", "text not null default '{}'")
        self._db.commit()

    @property
    def path(self):
        return self._path

    def _ensure_column(self, name, definition):
        columns = {row[1] for row in self._db.execute("pragma table_info(runs)")}
        if name not in columns:
            self._db.execute("alter table runs add column {0} {1}".format(name, definition))

    def save_run(self, run):
        with self._lock:
            self._db.execute(
                """
                insert into runs(run_id, thread_id, status, request_json, state_json, report_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                    thread_id=excluded.thread_id,
                    status=excluded.status,
                    request_json=excluded.request_json,
                    state_json=excluded.state_json,
                    report_json=excluded.report_json,
                    updated_at=excluded.updated_at
                """,
                (
                    run.run_id,
                    run.thread_id,
                    run.status,
                    _json_dumps(run.request),
                    _json_dumps(run.state),
                    _json_dumps(run.state.get("report", {})),
                    run.created_at,
                    run.updated_at,
                ),
            )
            self._db.commit()

    def load_run(self, run_id):
        with self._lock:
            row = self._db.execute(
                """
                select run_id, thread_id, status, request_json, state_json, created_at, updated_at
                from runs where run_id = ?
                """,
                (run_id,),
            ).fetchone()
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


class RunRecord:
    def __init__(
        self,
        request,
        run_id=None,
        thread_id=None,
        status="queued",
        state=None,
        created_at=None,
        updated_at=None,
    ):
        self.run_id = run_id or uuid.uuid4().hex
        self.thread_id = thread_id or request.get("thread_id") or uuid.uuid4().hex
        self.status = status
        self.created_at = created_at or utc_now()
        self.updated_at = updated_at or self.created_at
        self.request = dict(request or {})
        self.state = state or self._build_initial_state(self.request)
        self.state.setdefault("run_id", self.run_id)
        self.state.setdefault("thread_id", self.thread_id)
        self.events = []
        self.condition = threading.Condition()
        self.terminal = self.status in ("completed", "error")
        self.approval_event = threading.Event()
        self.tool_result_event = threading.Event()
        self.pending_decision = None
        self.pending_decision_payload = {}
        self.pending_tool_result = None

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
        module = cls._extract_number(
            feedback,
            r"module\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)",
            float(op.get("module", 2.0)),
        )
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
            "thickness": float(
                cls._extract_number(prompt, r"(?:thickness|height)\s*(?:of|=)?\s*([0-9]+(?:\.[0-9]+)?)", 8.0)
            ),
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

    @property
    def last_error(self):
        return self._error

    def explain(self, state):
        if not self.available:
            return {"assistant_text": "", "assistant_phase": state.get("assistant_phase", ""), "previous_response_id": state.get("previous_response_id", "")}

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
            "issues": issues[:10],
            "objects": snapshot.get("objects", [])[:20],
            "selection": snapshot.get("selection", []),
            "tool_results": state.get("tool_results", [])[-3:],
        }
        system_prompt = (
            "You are MagicCAD AI. Provide concise, actionable CAD review feedback for a FreeCAD-based desktop tool. "
            "If you need more detail, call a read-only tool. Never ask to run arbitrary Python. "
            "When you answer directly, return clear prose only."
        )
        kwargs = {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload)}]},
            ],
            "tools": READ_ONLY_TOOL_SPECS,
        }
        previous_response_id = state.get("previous_response_id", "")
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        try:
            response = self._client.responses.create(**kwargs)
            parsed = self._parse_response(response)
            parsed.setdefault("assistant_phase", phase)
            return parsed
        except Exception as exc:
            self._error = str(exc)
            return {"assistant_text": "", "assistant_phase": phase, "previous_response_id": previous_response_id}

    def _parse_response(self, response):
        text = getattr(response, "output_text", "") or ""
        tool_request = None
        for item in getattr(response, "output", []) or []:
            item_type = _field(item, "type")
            if item_type == "function_call":
                arguments = _safe_json_loads(_field(item, "arguments", "{}"), {})
                tool_request = {
                    "request_id": uuid.uuid4().hex,
                    "call_id": _field(item, "call_id", ""),
                    "tool_name": _field(item, "name", ""),
                    "arguments": arguments,
                }
                break
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

    @property
    def last_error(self):
        return self._error

    def explain(self, state):
        if not self.available:
            return {"assistant_text": "", "assistant_phase": state.get("assistant_phase", ""), "previous_response_id": state.get("previous_response_id", "")}

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
            "issues": issues[:10],
            "objects": snapshot.get("objects", [])[:20],
            "selection": snapshot.get("selection", []),
            "tool_results": state.get("tool_results", [])[-3:],
        }
        system_prompt = (
            "You are MagicCAD AI. Provide concise, actionable CAD review feedback for a FreeCAD-based desktop tool. "
            "If you need more detail, call a read-only tool. Never ask to run arbitrary Python. "
            "When you answer directly, return clear prose only."
        )
        try:
            if self._model is None or self._model.name != model_name:
                self._model = self._client.GenerativeModel(model_name)
            model = self._model
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
            parsed = self._parse_response(response)
            parsed.setdefault("assistant_phase", phase)
            parsed["previous_response_id"] = model_name
            return parsed
        except Exception as exc:
            self._error = str(exc)
            return {"assistant_text": "", "assistant_phase": phase, "previous_response_id": model_name}

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

    def _parse_response(self, response):
        """Parse Gemini API response to match OpenAI response format."""
        text = ""
        tool_request = None

        try:
            if hasattr(response, "text") and response.text:
                text = response.text.strip()

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


class LangGraphRuntime:
    def __init__(self, engine, database_path):
        self._engine = engine
        self.available = False
        self.error = ""
        self._compiled = None
        self._command_cls = None
        self._interrupt_fn = None
        self._checkpointer = None
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            from langgraph.graph import END, START, StateGraph
            from langgraph.types import Command, interrupt
        except Exception as exc:
            self.error = str(exc)
            return

        try:
            self._checkpointer = SqliteSaver.from_conn_string(database_path)
        except Exception:
            try:
                self._checkpointer = SqliteSaver(sqlite3.connect(database_path, check_same_thread=False))
            except Exception as exc:
                self.error = str(exc)
                return

        graph = StateGraph(dict)
        graph.add_node("intake", self._wrap("intake", engine.intake))
        graph.add_node("normalize_snapshot", self._wrap("normalize_snapshot", engine.normalize_snapshot))
        graph.add_node("deterministic_validate", self._wrap("deterministic_validate", engine.deterministic_validate))
        graph.add_node("llm_explain", self._wrap("llm_explain", engine.llm_explain))
        graph.add_node("draft_plan", self._wrap("draft_plan", engine.draft_plan))
        graph.add_node("approval_gate", self._wrap("approval_gate", engine.approval_gate))
        graph.add_node("tool_dispatch", self._wrap("tool_dispatch", engine.tool_dispatch))
        graph.add_node("report_render", self._wrap("report_render", engine.report_render))
        graph.add_node("complete", self._wrap("complete", engine.complete))
        graph.add_edge(START, "intake")
        graph.add_edge("intake", "normalize_snapshot")
        graph.add_edge("normalize_snapshot", "deterministic_validate")
        graph.add_edge("deterministic_validate", "llm_explain")
        graph.add_conditional_edges(
            "llm_explain",
            self._engine.route_after_llm_explain,
            {"draft_plan": "draft_plan", "tool_dispatch": "tool_dispatch"},
        )
        graph.add_conditional_edges(
            "draft_plan",
            self._engine.route_after_draft_plan,
            {
                "approval_gate": "approval_gate",
                "tool_dispatch": "tool_dispatch",
                "report_render": "report_render",
            },
        )
        graph.add_conditional_edges(
            "approval_gate",
            self._engine.route_after_approval_gate,
            {
                "draft_plan": "draft_plan",
                "tool_dispatch": "tool_dispatch",
                "report_render": "report_render",
            },
        )
        graph.add_conditional_edges(
            "tool_dispatch",
            self._engine.route_after_tool_dispatch,
            {
                "llm_explain": "llm_explain",
                "draft_plan": "draft_plan",
                "report_render": "report_render",
            },
        )
        graph.add_edge("report_render", "complete")
        graph.add_edge("complete", END)

        try:
            self._compiled = graph.compile(checkpointer=self._checkpointer)
            self._command_cls = Command
            self._interrupt_fn = interrupt
            self.available = True
        except Exception as exc:
            self.error = str(exc)
            self._compiled = None

    def interrupt(self, payload):
        if not self.available or self._interrupt_fn is None:
            raise RuntimeError("LangGraph interrupt is not available")
        return self._interrupt_fn(payload)

    def initial_invoke(self, state, config):
        if not self.available or self._compiled is None:
            return state
        return self._compiled.invoke(state, config=config)

    def resume_invoke(self, resume_payload, config):
        if not self.available or self._compiled is None or self._command_cls is None:
            return resume_payload
        return self._compiled.invoke(self._command_cls(resume=resume_payload), config=config)

    def current_state(self, config, fallback):
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
        self._openai_responder = OpenAIResponder()
        self._gemini_responder = GeminiResponder()
        self._local = threading.local()
        self._langgraph = LangGraphRuntime(self, self._store.path)

    def _get_responder(self, state):
        """Get the appropriate responder based on model selection."""
        model = state.get("model", DEFAULT_MODEL)
        provider = _get_model_provider(model)
        if provider == "gemini":
            return self._gemini_responder, "gemini"
        return self._openai_responder, "openai"

    @property
    def langgraph_available(self):
        return self._langgraph.available

    @property
    def current_run(self):
        return getattr(self._local, "run", None)

    def start_run(self, run):
        if self._langgraph.available:
            self._drive_graph(run, mode="start")
            return
        self._process_without_langgraph(run)

    def resume_approval(self, run, decision, payload):
        if self._langgraph.available:
            self._drive_graph(run, mode="resume", resume_payload={"decision": decision, "payload": payload or {}})
            return
        run.pending_decision = decision
        run.pending_decision_payload = payload or {}
        run.approval_event.set()
        self._persist(run)

    def resume_tool(self, run, payload):
        if self._langgraph.available:
            self._drive_graph(run, mode="tool", resume_payload=payload or {})
            return
        run.pending_tool_result = payload or {}
        run.tool_result_event.set()
        self._persist(run)

    def publish_node(self, node_name, status):
        run = self.current_run
        if run is not None:
            self._publish(run, "node_status", node=node_name, status=status)

    def intake(self, state):
        summary = "Intake complete for {0} objects.".format(len(state.get("snapshot", {}).get("objects", [])))
        return {"assistant_phase": "intake", "summary": summary}

    def normalize_snapshot(self, state):
        snapshot = dict(state.get("snapshot", {}) or {})
        snapshot.setdefault("objects", [])
        snapshot.setdefault("selection", [])
        snapshot.setdefault("dependency_edges", [])
        snapshot.setdefault("recompute_errors", [])
        return {"assistant_phase": "normalize_snapshot", "snapshot": snapshot}

    def deterministic_validate(self, state):
        issues = Validators.validate_snapshot(state.get("snapshot", {}))
        run = self.current_run
        if run is not None:
            self._publish(run, "issues_delta", issues=issues)
        return {
            "assistant_phase": "deterministic_validate",
            "issues": issues,
            "issue_counts": Validators.issue_counts(issues),
        }

    def llm_explain(self, state):
        responder, provider = self._get_responder(state)
        explanation = responder.explain(state)
        text = explanation.get("assistant_text", "")
        if not text:
            text = self._fallback_explanation(state.get("snapshot", {}), state.get("issues", []), state.get("prompt", ""))
        run = self.current_run
        if run is not None and text:
            self._publish(run, "assistant_delta", text=text, phase=explanation.get("assistant_phase", "llm_explain"))
        updates = {
            "assistant_phase": explanation.get("assistant_phase", "llm_explain") or "llm_explain",
            "assistant_text": text,
            "previous_response_id": explanation.get("previous_response_id", state.get("previous_response_id", "")),
            "pending_tool_request": explanation.get("pending_tool_request"),
            "tool_return_to": explanation.get("tool_return_to", ""),
            "backend": {
                "openai": self._openai_responder.available,
                "gemini": self._gemini_responder.available,
                "langgraph": self._langgraph.available,
                "model": state.get("model", DEFAULT_MODEL),
                "provider": provider,
            },
        }
        return updates

    def draft_plan(self, state):
        feedback = (state.get("approval_feedback", "") or "").strip()
        proposed_changes = state.get("proposed_changes", [])
        if feedback and proposed_changes:
            changes = PromptInterpreter.revise_changes(proposed_changes, feedback)
        else:
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

    def approval_gate(self, state):
        proposed_changes = state.get("proposed_changes", [])
        if not proposed_changes:
            return {"approval_status": "not_required"}

        run = self.current_run
        if run is None:
            return {"approval_status": "rejected"}

        self._set_status(run, "awaiting_approval")
        request = {
            "interrupt_kind": "approval",
            "message": "Approval is required before MagicCAD AI applies local document changes.",
            "proposed_changes": proposed_changes,
        }
        self._publish(run, "approval_required", **request)
        decision_payload = self._langgraph.interrupt(request)
        self._set_status(run, "running")

        decision = _field(decision_payload, "decision", "reject")
        payload = _field(decision_payload, "payload", {}) or {}
        if decision == "edit":
            feedback = payload.get("feedback", "")
            self._publish(run, "assistant_delta", text="Revising the proposed draft based on the latest feedback.", phase="approval")
            return {
                "approval_status": "edited",
                "approval_feedback": feedback,
            }
        if decision == "approve":
            selected = self._select_change(proposed_changes, payload.get("change_id", ""))
            request_id = uuid.uuid4().hex
            return {
                "approval_status": "approved",
                "applied_change": selected,
                "pending_tool_request": {
                    "request_id": request_id,
                    "tool_name": "apply_ops",
                    "arguments": {"ops": selected.get("ops", [])},
                    "interrupt_kind": "tool",
                },
                "tool_return_to": "report_render",
            }
        return {"approval_status": "rejected"}

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

        request = dict(tool_request)
        request.setdefault("interrupt_kind", "tool")
        self._set_status(run, "awaiting_tool")
        self._publish(run, "tool_request", **request, return_node=state.get("tool_return_to", ""))
        tool_result = self._langgraph.interrupt(request)
        self._set_status(run, "running")

        collected = list(state.get("tool_results", []))
        collected.append(tool_result or {"result": {"ok": False, "error": "No tool result received"}})
        result_ok = _field(_field(tool_result, "result", {}), "ok", False)
        if request.get("tool_name") == "apply_ops":
            if result_ok:
                self._publish(run, "assistant_delta", text="Approved change applied locally and recomputed.", phase="tool")
            else:
                self._publish(
                    run,
                    "assistant_delta",
                    text="Approved change failed locally: {0}".format(_field(_field(tool_result, "result", {}), "error", "unknown error")),
                    phase="tool",
                )
        return {
            "pending_tool_request": None,
            "tool_results": collected,
        }

    def report_render(self, state):
        return {
            "assistant_phase": "report_render",
            "report": self._render_report(state),
        }

    def complete(self, state):
        return {"assistant_phase": "complete"}

    def route_after_llm_explain(self, state):
        return "tool_dispatch" if state.get("pending_tool_request") else "draft_plan"

    def route_after_draft_plan(self, state):
        if state.get("pending_tool_request"):
            return "tool_dispatch"
        if state.get("proposed_changes"):
            return "approval_gate"
        return "report_render"

    def route_after_approval_gate(self, state):
        if state.get("approval_status") == "edited":
            return "draft_plan"
        if state.get("pending_tool_request"):
            return "tool_dispatch"
        return "report_render"

    def route_after_tool_dispatch(self, state):
        return state.get("tool_return_to", "") or "report_render"

    def _drive_graph(self, run, mode, resume_payload=None):
        self._local.run = run
        try:
            config = {"configurable": {"thread_id": run.thread_id}}
            if mode == "start":
                run.status = "running"
                self._persist(run)
                self._publish(run, "run_started", status="running")
                result = self._langgraph.initial_invoke(dict(run.state), config)
            else:
                run.status = "running"
                self._persist(run)
                result = self._langgraph.resume_invoke(resume_payload or {}, config)

            graph_state = self._langgraph.current_state(config, result if isinstance(result, dict) else run.state)
            if isinstance(graph_state, dict):
                run.state.update(graph_state)
            self._persist(run)
            if run.status in ("awaiting_approval", "awaiting_tool"):
                return
            run.state["report"] = run.state.get("report") or self._render_report(run.state)
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

    def _process_without_langgraph(self, run):
        self._local.run = run
        try:
            run.status = "running"
            self._persist(run)
            self._publish(run, "run_started", status="running")
            state = dict(run.state)
            for node_name, fn in (
                ("intake", self.intake),
                ("normalize_snapshot", self.normalize_snapshot),
                ("deterministic_validate", self.deterministic_validate),
                ("llm_explain", self.llm_explain),
                ("draft_plan", self.draft_plan),
            ):
                self.publish_node(node_name, "running")
                state.update(fn(state))
                self.publish_node(node_name, "completed")
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

    def _approval_loop(self, run, state):
        proposed_changes = list(state.get("proposed_changes", []))
        while proposed_changes:
            self._set_status(run, "awaiting_approval")
            run.approval_event.clear()
            self._publish(
                run,
                "approval_required",
                proposed_changes=proposed_changes,
                message="Approval is required before MagicCAD AI applies local document changes.",
                interrupt_kind="approval",
            )
            run.approval_event.wait()
            decision = run.pending_decision or "reject"
            payload = run.pending_decision_payload or {}
            run.pending_decision = None
            run.pending_decision_payload = {}
            self._set_status(run, "running")

            if decision == "reject":
                state["approval_status"] = "rejected"
                state["proposed_changes"] = proposed_changes
                return state
            if decision == "edit":
                proposed_changes = PromptInterpreter.revise_changes(proposed_changes, payload.get("feedback", ""))
                state["proposed_changes"] = proposed_changes
                state["approval_status"] = "edited"
                self._publish(run, "assistant_delta", text="Revised the proposed draft based on the latest feedback.", phase="approval")
                continue

            selected = self._select_change(proposed_changes, payload.get("change_id", ""))
            request_id = uuid.uuid4().hex
            run.tool_result_event.clear()
            self._set_status(run, "awaiting_tool")
            self._publish(
                run,
                "tool_request",
                request_id=request_id,
                tool_name="apply_ops",
                arguments={"ops": selected.get("ops", [])},
                interrupt_kind="tool",
                return_node="report_render",
            )
            run.tool_result_event.wait()
            tool_result = run.pending_tool_result or {"result": {"ok": False, "error": "No tool result received"}}
            run.pending_tool_result = None
            self._set_status(run, "running")
            state.setdefault("tool_results", []).append(tool_result)
            state["approval_status"] = "approved" if _field(_field(tool_result, "result", {}), "ok", False) else "failed"
            state["applied_change"] = selected
            state["proposed_changes"] = proposed_changes
            if _field(_field(tool_result, "result", {}), "ok", False):
                self._publish(run, "assistant_delta", text="Approved change applied locally and recomputed.", phase="tool")
            else:
                self._publish(
                    run,
                    "assistant_delta",
                    text="Approved change failed locally: {0}".format(_field(_field(tool_result, "result", {}), "error", "unknown error")),
                    phase="tool",
                )
            return state
        return state

    def _select_change(self, proposed_changes, change_id):
        if not proposed_changes:
            return {}
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
            summary += " Highest priority: {0}".format(issues[0].get("message", ""))
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
                ok = _field(_field(result, "result", {}), "ok", False)
                message = "Applied successfully" if ok else _field(_field(result, "result", {}), "error", "Failed")
                markdown_lines.append("- {0}".format(message))
            markdown_lines.append("")

        markdown = "\n".join(markdown_lines).strip() + "\n"
        html = "<html><body><pre>{0}</pre></body></html>".format(html_lib.escape(markdown))
        return {
            "report_id": uuid.uuid4().hex,
            "thread_id": state.get("thread_id", ""),
            "snapshot_hash": state.get("snapshot", {}).get("snapshot_hash", ""),
            "summary": summary,
            "assistant_phase": state.get("assistant_phase", ""),
            "previous_response_id": state.get("previous_response_id", ""),
            "issue_counts": counts,
            "issues": issues,
            "proposed_changes": proposed_changes,
            "model_info": {
                "requested_model": state.get("model", DEFAULT_MODEL),
                "openai_enabled": self._openai_responder.available,
                "gemini_enabled": self._gemini_responder.available,
                "langgraph_enabled": self._langgraph.available,
                "langgraph_error": self._langgraph.error,
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

    def _set_status(self, run, status):
        run.status = status
        run.updated_at = utc_now()
        self._persist(run)


class ServerState:
    def __init__(self, database_path):
        self._store = SQLiteRunStore(database_path)
        self._engine = MagicCADAgentEngine(self._store)
        self._runs = {}
        self._lock = threading.Lock()

    def health(self):
        return {
            "ok": True,
            "status": "ready",
            "timestamp": utc_now(),
            "langgraph_enabled": self._engine.langgraph_available,
            "backends": {
                "openai": self._engine._openai_responder.available,
                "gemini": self._engine._gemini_responder.available,
            },
            "errors": {
                "openai": self._engine._openai_responder.last_error if not self._engine._openai_responder.available else "",
                "gemini": self._engine._gemini_responder.last_error if not self._engine._gemini_responder.available else "",
            },
        }

    def create_run(self, request):
        run = RunRecord(request)
        with self._lock:
            self._runs[run.run_id] = run
        self._store.save_run(run)
        worker = threading.Thread(target=self._engine.start_run, args=(run,), daemon=True)
        worker.start()
        return run

    def get_run(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
        if run is not None:
            return run
        restored = self._store.load_run(run_id)
        if restored is None:
            return None
        with self._lock:
            self._runs[run_id] = restored
        return restored

    def resume_run(self, run_id, decision, payload):
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        worker = threading.Thread(target=self._engine.resume_approval, args=(run, decision, payload or {}), daemon=True)
        worker.start()
        return {"ok": True, "run_id": run_id, "status": run.status}

    def submit_tool_results(self, run_id, payload):
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        worker = threading.Thread(target=self._engine.resume_tool, args=(run, payload or {}), daemon=True)
        worker.start()
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


def _field(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _safe_json_loads(text, default):
    try:
        if isinstance(text, (dict, list)):
            return text
        if text is None:
            return default
        return json.loads(text)
    except Exception:
        return default


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
