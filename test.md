# MagicCAD AI Manual Test Guide

This document is the manual test checklist for the `MagicCADAI` workbench in this repository.

It is written for the current local debug build:

```bash
/Users/jagjeevankashid/Developer/hackethon/MagicCAD/build/debug/bin/FreeCAD
```

## Scope

Use this guide to manually test:

- workbench loading
- dock panel opening
- deterministic validation
- selection-aware validation
- copilot prompt flow
- draft approval flow
- report export flow
- error handling
- optional OpenAI and LangGraph integration

## Preconditions

Before testing, make sure:

- you are on the project repo root:
  ```bash
  cd /Users/jagjeevankashid/Developer/hackethon/MagicCAD
  ```
- the debug build exists
- the `MagicCAD AI` workbench appears in the workbench selector
- FreeCAD launches with:
  ```bash
  /Users/jagjeevankashid/Developer/hackethon/MagicCAD/build/debug/bin/FreeCAD
  ```

Optional AI setup:

- install Python packages into the active environment if you want LLM-backed explanations:
  ```bash
  pixi run python -m pip install openai langgraph
  ```
- set an API key before launching FreeCAD:
  ```bash
  export OPENAI_API_KEY=your_key_here
  ```

Notes:

- the macOS Qt warning about `.AppleSystemUIFont` can be ignored unless UI text is broken
- if OpenAI is not configured, deterministic validation should still work

## Test 1: Workbench Loads

Goal: confirm the workbench registers and loads cleanly.

Steps:

1. Launch FreeCAD.
2. Open the workbench dropdown.
3. Select `MagicCAD AI`.

Expected:

- `MagicCAD AI` is present in the dropdown
- the `MagicCAD AI` top-level menu is visible
- the toolbar for MagicCAD AI is visible
- no startup traceback is printed in the launching terminal

Failure signals:

- workbench missing from dropdown
- traceback mentioning `InitGui.py`
- missing command icons or broken toolbar actions

## Test 2: Open The Dock Panel

Goal: confirm the panel controller and dock widget load.

Steps:

1. In the `MagicCAD AI` workbench, click `MagicCAD AI > Open MagicCAD AI`.

Expected:

- a right-side dock panel opens
- the panel contains `Copilot`, `Issues`, and `Report` tabs
- no traceback is printed in the terminal

Failure signals:

- no panel opens
- popup error dialog
- traceback mentioning `Commands.py`, `DockPanel.py`, or `BridgeClient.py`

## Test 3: Empty Document Validation

Goal: verify baseline full-document validation.

Steps:

1. Start a new `Empty File`.
2. Open the MagicCAD AI panel.
3. Click `Validate Document`.

Expected:

- a run starts in the panel
- the run completes without freezing the UI
- the `Report` tab shows a summary
- the `Issues` tab shows either no issues or low-confidence/document-level issues

What to verify:

- the app remains responsive
- no crash occurs
- the report content updates after the run

## Test 4: Selection Validation

Goal: verify focused validation for selected objects.

Steps:

1. Create a new `Parametric Body`.
2. Select the body in the model tree.
3. Open the MagicCAD AI panel.
4. Click `Validate Selection`.

Expected:

- a validation run starts
- the run is scoped to the selected object
- the `Issues` tab only references the selected object or its neighborhood

Failure signals:

- selection is ignored
- validation behaves exactly like full-document validation on every run

## Test 5: Simple Sketch / Partial Model Validation

Goal: verify the deterministic validators detect common modeling issues.

Steps:

1. Create a `Body`.
2. Create a new `Sketch`.
3. Add a few lines or circles, but do not necessarily make a complete valid profile.
4. Close the sketch.
5. Click `Validate Document`.

Expected:

- the validator reports sketch incompleteness, fragile geometry, or related warnings when applicable
- the report mentions the affected object by name
- the issue can be selected from the `Issues` tab

What to verify:

- issue severity is shown
- issue text is readable and actionable
- selecting the issue attempts to navigate to the target object

## Test 6: Recompute / Broken Feature Detection

Goal: verify recompute-related errors surface in the report.

Steps:

1. Create a body and sketch a valid closed profile.
2. Create a `Pad`.
3. Edit the sketch so the profile becomes invalid for the pad.
4. Recompute the document if needed.
5. Run `Validate Document`.

Expected:

- recompute failure or model inconsistency appears in the report
- the failing feature is identified
- the issue severity is medium or high depending on the state

## Test 7: Duplicate Labels / Naming Consistency

Goal: verify metadata consistency checks.

Steps:

1. Create two objects.
2. Rename them to the same or confusingly similar label if FreeCAD allows it.
3. Run `Validate Document`.

Expected:

- the report flags naming ambiguity or consistency warnings if detected

## Test 8: Issue Highlighting

Goal: verify issue-to-model navigation.

Steps:

1. Produce at least one issue using the tests above.
2. In the `Issues` tab, select the issue.
3. Trigger highlight/navigation if the panel exposes a button or item action.

Expected:

- the target object becomes selected or emphasized
- the camera focuses on the affected object when possible
- highlighting clears or updates when another issue is selected

Failure signals:

- clicking an issue does nothing
- wrong object is selected
- repeated highlighting leaves the UI in a broken visual state

## Test 9: Copilot Prompt To Draft

Goal: verify prompt handling and draft proposal generation.

Steps:

1. Start with a new empty file.
2. Open the MagicCAD AI panel.
3. Enter this prompt:

```text
Create a gear with 10 teeth, module 2 mm, thickness 8 mm, and 6 mm center bore.
```

4. Run the copilot action from the panel.

Expected:

- a run starts
- the panel shows progress or reasoning steps
- a proposed draft appears instead of immediate silent model mutation
- the report or copilot panel references a gear creation plan

Notes:

- this flow is designed to work even without OpenAI for the local gear path

## Test 10: Draft Approval And Apply

Goal: verify approval-gated model mutation.

Steps:

1. Complete Test 9 until a draft is proposed.
2. Click `Apply Draft`.

Expected:

- the document changes only after the apply action
- a gear-like model is created
- the document recomputes successfully
- a follow-up validation can run on the new geometry

What to verify:

- body or feature objects appear in the model tree
- no silent mutation happens before approval
- errors are surfaced cleanly if creation fails

## Test 11: Revalidate Generated Geometry

Goal: verify the system can validate AI-created output.

Steps:

1. After applying the gear draft, click `Validate Document`.

Expected:

- a report is generated for the newly created model
- issues, if any, are tied to the created objects
- the panel remains usable after a mutation workflow

## Test 12: Export Report

Goal: verify validation report export.

Steps:

1. Run any successful validation.
2. Click `Export Report`.
3. Save the report to a known location.

Expected:

- a report file is written successfully
- the saved report contains structured information about the run
- repeated exports do not crash the panel

What to check:

- output file exists
- output is not empty
- report summary, issues, and metadata are present

## Test 13: Document Persistence

Goal: verify AI session/report data survives a save and reopen cycle.

Steps:

1. Create or validate a document so the panel has report data.
2. Save the FreeCAD document.
3. Close the document.
4. Reopen it.
5. Open the MagicCAD AI panel again.

Expected:

- session/report objects remain available if persistence is implemented correctly
- the panel can continue operating on the reopened document

## Test 14: Sidecar Restart / Recovery

Goal: verify the sidecar process can recover.

Steps:

1. Open the panel and run one successful action.
2. If you know the sidecar process PID, terminate it externally.
3. Run another validation action from the panel.

Expected:

- the panel reconnects or restarts the sidecar
- the UI does not freeze permanently
- a clear error is shown if automatic recovery fails

## Test 15: No API Key Behavior

Goal: verify graceful degradation when OpenAI is not configured.

Steps:

1. Ensure `OPENAI_API_KEY` is unset.
2. Launch FreeCAD.
3. Run `Validate Document`.
4. Run the gear prompt flow.

Expected:

- deterministic validation still works
- local prompt-driven draft flows that do not require OpenAI still work
- the UI explains when AI-enhanced reasoning is unavailable

## Test 16: With OpenAI Enabled

Goal: verify the optional LLM-backed path.

Steps:

1. Set `OPENAI_API_KEY`.
2. Ensure `openai` and optionally `langgraph` are installed in the same environment used by FreeCAD.
3. Relaunch FreeCAD.
4. Run `Validate Document`.
5. Run the gear prompt flow again.

Expected:

- explanations become richer
- the run still completes cleanly
- tool-driven actions remain approval-gated

What to verify:

- no API auth error
- no JSON/schema parsing error
- no UI freeze during streaming or result handling

## Test 17: Invalid Prompt Handling

Goal: verify resilience against vague or impossible requests.

Steps:

1. Enter a vague prompt such as:

```text
Make something cool.
```

2. Run the copilot action.

Expected:

- the system asks for clarification or returns a constrained response
- it does not mutate the document blindly
- the panel remains stable

## Test 18: Multi-Run Stability

Goal: verify the panel stays healthy across repeated runs.

Steps:

1. Open one document.
2. Run `Validate Document` three to five times.
3. Run a selection validation.
4. Run a copilot draft request.
5. Export a report.

Expected:

- no duplicate dock panels are created
- no runaway sidecar processes appear
- memory or responsiveness does not degrade sharply

## Suggested Test Order

Use this order for practical manual QA:

1. Test 1: Workbench Loads
2. Test 2: Open The Dock Panel
3. Test 3: Empty Document Validation
4. Test 4: Selection Validation
5. Test 5: Simple Sketch / Partial Model Validation
6. Test 8: Issue Highlighting
7. Test 9: Copilot Prompt To Draft
8. Test 10: Draft Approval And Apply
9. Test 11: Revalidate Generated Geometry
10. Test 12: Export Report
11. Test 13: Document Persistence
12. Test 15 or Test 16 depending on whether OpenAI is configured

## Terminal Checks During Testing

Keep the launch terminal visible while testing. Watch for:

- Python tracebacks
- sidecar startup messages
- missing import errors
- serialization or OpenAI API errors

Useful launch command:

```bash
/Users/jagjeevankashid/Developer/hackethon/MagicCAD/build/debug/bin/FreeCAD
```

## Bug Report Template

When a test fails, capture:

- test case name
- exact step number
- screenshot
- terminal traceback
- whether `OPENAI_API_KEY` was set
- whether a document was empty, partial, or fully modeled

Use this format:

```text
Test:
Step:
What I clicked:
Expected:
Actual:
Terminal traceback:
Screenshot:
```

## Current Known Risks

At the moment, keep these in mind while testing:

- the full CMake rebuild path is currently blocked by an unrelated Qt `uic` configure error in this environment
- the workbench runtime files in `build/debug/Mod/MagicCADAI` were patched directly for local testing
- some flows may degrade to deterministic-only behavior when OpenAI or LangGraph is not installed
