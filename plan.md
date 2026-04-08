# MagicCAD AI Copilot + Validation Architecture

## Summary

- Build a new Python-first module, `MagicCADAI`, under `src/Mod`, following the same extension seams already used for workbench registration, dockable UI, and document observers in `src/Mod/Inspection/InitGui.py`, `src/Mod/Help/Help.py`, and `src/Mod/Show/TVObserver.py`.
- Keep FreeCAD integration in-process and run LangGraph orchestration in a local sidecar service. The desktop module owns UI, observers, snapshot extraction, highlights, and safe tool execution; the sidecar owns LangGraph state, OpenAI calls, streaming, approvals, and report assembly.
- Use `gpt-5.4` as the primary model. Reserve `gpt-5.4-pro` for slower on-demand deep review, and use `gpt-5.4-mini` only for cheap background triage. Use the OpenAI Responses API, preserve `previous_response_id`, and round-trip assistant `phase` values for long-running, tool-heavy flows.
- Implement the agent as a custom LangGraph `StateGraph`, not a prebuilt agent, because this workflow mixes deterministic validation, durable execution, streaming, and human approval for mutating CAD actions. Persist runs with a SQLite checkpointer in the local sidecar and use LangGraph interrupts for approval and resume.

## Implementation Changes

- Create `src/Mod/MagicCADAI/CMakeLists.txt` and enable it from `src/Mod/CMakeLists.txt` behind `BUILD_MAGICCAD_AI`. Copy and install Python files, icons, and UI assets with the existing FreeCAD build macros.
- Add desktop files `Init.py`, `InitGui.py`, `Commands.py`, `DockPanel.py`, `Observers.py`, `Snapshot.py`, `Highlighting.py`, `BridgeClient.py`, `ToolRegistry.py`, and `SessionObjects.py`.
- Register commands `MagicCADAI_Open`, `MagicCADAI_ValidateDocument`, `MagicCADAI_ValidateSelection`, `MagicCADAI_ApplyDraft`, and `MagicCADAI_ExportReport`.
- Build one persistent right-side dock with three panes: `Copilot`, `Issues`, and `Report`. Use standard PySide widgets plus a `QThread` SSE consumer; do not make the core panel depend on QtWebEngine.
- Launch the sidecar with `QProcess` on first panel open, watchdog it, and reconnect automatically. Expose only `GET /health`, `POST /v1/runs`, `GET /v1/runs/{run_id}/events`, `POST /v1/runs/{run_id}/tool-results`, and `POST /v1/runs/{run_id}/resume`.
- Register `FreeCAD.addDocumentObserver` and `FreeCADGui.Selection.addObserver`, maintain a debounced snapshot cache per document, and trigger:
  - incremental validation on selection, recompute, and change-neighborhood updates
  - full validation on explicit command and after approved draft application
- Use `DocumentSnapshot` as the only payload sent to the sidecar. Do not send full FCStd or BREP by default; send structural and metric JSON, then let the sidecar request targeted read-only tool calls when it needs more detail.
- Run deterministic validators before any LLM step. V1 rule packs are: sketch integrity, parametric consistency, recompute failures, null and non-solid shapes, dependency and orphan issues, tiny-edge and tiny-face risk, wall-thickness and radius heuristic warnings, and naming and unit inconsistencies.
- Use a custom LangGraph graph with nodes `intake`, `normalize_snapshot`, `deterministic_validate`, `llm_explain`, `draft_plan`, `approval_gate`, `report_render`, and `complete`.
- `llm_explain` uses OpenAI Responses API function calling with an explicit allowed-tools list. The sidecar never touches FreeCAD objects directly; it emits `tool_request` events and waits for the desktop module to execute whitelisted tools locally.
- Any mutating action always passes through `approval_gate`. Resume values are only `approve`, `edit`, or `reject`; rejected actions are added back into graph state so the planner can revise instead of starting over.
- Persist per-document state with two Python document objects:
  - `MagicCADAI::Session` for thread id, model config, and last run metadata
  - `MagicCADAI::ValidationReport` for structured report JSON, rendered HTML or Markdown, issue index, and snapshot hash
- Highlight issues in-model by selecting the target object or subelement, focusing the camera, and applying temporary view styling. If a subelement ref is unavailable, fall back to whole-object highlight.

## Public Interfaces

### `DocumentSnapshot`

- `document_id`
- `document_label`
- `units`
- `active_workbench`
- `active_object_id`
- `selection`
- `parameters[]`
- `objects[]`
- `dependency_edges[]`
- `recompute_errors[]`
- `snapshot_hash`

### `ValidationIssue`

- `issue_id`
- `rule_id`
- `severity`
- `category`
- `source`
- `confidence`
- `object_ref`
- `subelement_ref`
- `evidence`
- `message`
- `recommended_fix`
- `highlight_mode`

### `ProposedChange`

- `change_id`
- `summary`
- `risk_level`
- `ops[]`
- `ops[]` are typed, whitelisted CAD actions only:
  - `create_body`
  - `create_sketch`
  - `add_line`
  - `add_circle`
  - `add_rectangle`
  - `pad`
  - `pocket`
  - `fillet`
  - `chamfer`
  - `boolean_union`
  - `boolean_cut`
  - `set_parameter`
  - `rename_object`
  - `recompute`
- Do not allow arbitrary Python execution in v1.

### `ValidationReport`

- `report_id`
- `thread_id`
- `snapshot_hash`
- `summary`
- `issue_counts`
- `issues[]`
- `proposed_changes[]`
- `model_info`
- `rulepack_version`
- `created_at`
- `html`
- `markdown`

### Sidecar event stream

- `run_started`
- `node_status`
- `assistant_delta`
- `issues_delta`
- `tool_request`
- `approval_required`
- `report_ready`
- `run_finished`
- `run_error`

## Test Plan

- Workbench and bootstrap
  - Opening the AI panel starts the sidecar once, reconnects after crash, and never blocks the FreeCAD UI thread.
  - Saving, closing, and reopening a document restores the same assistant thread and last report.
- Real-time analysis
  - Selection changes and recomputes trigger incremental validation for the changed object neighborhood.
  - Full-document validation produces structured issues with working object and subelement navigation and highlight restore.
- Agent safety
  - Read-only tool calls auto-run.
  - Mutating tool calls always interrupt and require explicit approval.
  - `reject` and `edit` resume the same LangGraph thread instead of creating a new run.
  - Schema-broken model output is rejected and surfaced as a non-fatal UI error.
- Draft generation and reports
  - A natural-language part request produces a `ProposedChange`, not raw Python.
  - Applying an approved change wraps the work in a FreeCAD transaction, recomputes, then automatically revalidates.
  - Exported reports round-trip as JSON plus HTML or Markdown and reopen correctly from stored `ValidationReport` objects.
- Failure modes
  - Missing API key, network errors, model rate limits, sidecar downtime, and malformed tool results all degrade to actionable UI errors without freezing the session or corrupting the document.

## Assumptions

- V1 is scoped to mechanical parts in `Sketcher`, `Part`, and `PartDesign`, with copilot plus validation behavior and human approval on every document mutation.
- The primary model is `gpt-5.4`; `gpt-5.4-pro` is manual or on-demand for deeper review; `gpt-5.4-mini` is only for low-cost background classification.
- The OpenAI integration uses the Responses API with `previous_response_id`, function calling, and assistant `phase`.
- The default local persistence backend is SQLite for LangGraph checkpoints because it fits the chosen local-sidecar topology.
- Report exports are JSON plus HTML or Markdown in v1; PDF export, assembly-specific validators, remote multi-user backends, and arbitrary Python or macro execution are out of scope for the first milestone.
