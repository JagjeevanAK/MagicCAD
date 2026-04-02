# MagicCAD AI - Implementation Documentation

## 📚 Documentation Index

This folder contains detailed implementation documentation for the MagicCAD AI project. Each file covers a specific component or aspect of the system.

---

## 📁 File Overview

| File | Description |
|------|-------------|
| `01_architecture_overview.md` | High-level system architecture and component relationships |
| `02_data_flow.md` | Complete data flow from user action to AI response |
| `03_snapshot_extraction.md` | How FreeCAD model data is extracted as JSON |
| `04_validators.md` | Rule-based design validation checks |
| `05_ai_integration.md` | OpenAI GPT API and LangGraph integration |
| `06_tool_registry.md` | CAD operations that AI can request |
| `07_approval_system.md` | Human approval gate mechanism |
| `08_ui_components.md` | Dock panel and UI implementation |
| `09_sidecar_server.md` | Sidecar server architecture and API |
| `10_session_persistence.md` | State persistence and session management |
| `11_langgraph_workflow.md` | LangGraph state machine workflow details |
| `12_gemini_integration.md` | **NEW** Google Gemini integration guide |

---

## 🎯 Quick Reference

### Core Source Files (FreeCAD Module)

```
src/Mod/MagicCADAI/
├── Init.py                    # Module initialization
├── InitGui.py                 # Workbench registration
├── Commands.py                # FreeCAD command definitions
├── DockPanel.py               # Main UI panel controller
├── Snapshot.py                # CAD data extraction to JSON
├── Validators.py              # Rule-based validation checks
├── ToolRegistry.py            # CAD operation implementations
├── BridgeClient.py            # HTTP client for sidecar communication
├── SidecarServer.py           # LangGraph + OpenAI server (separate process)
├── SessionObjects.py          # FreeCAD document storage objects
├── Observers.py               # Document and selection observers
├── Highlighting.py            # Issue highlighting in 3D view
├── QtCompat.py                # Qt/PySide compatibility layer
└── __init__.py                # Package initialization
```

### Key Architecture Components

| Component | File | Purpose |
|-----------|------|---------|
| **Snapshot Extractor** | `Snapshot.py` | Converts FreeCAD model to JSON |
| **Validators** | `Validators.py` | 9 rule-based design checks |
| **Tool Registry** | `ToolRegistry.py` | Executable CAD operations |
| **Bridge Client** | `BridgeClient.py` | FreeCAD ↔ Sidecar HTTP bridge |
| **Sidecar Server** | `SidecarServer.py` | LangGraph + OpenAI/Gemini orchestration |
| **Dock Panel** | `DockPanel.py` | User interface (Copilot, Issues, Report) |
| **Session Objects** | `SessionObjects.py` | Persistent storage in FreeCAD document |
| **Observers** | `Observers.py` | Watches for model changes |

---

## 🚀 Getting Started for AI Agents

If you're an AI agent reading this documentation to understand or modify the codebase:

### Step 1: Understand the Architecture
Start with `01_architecture_overview.md` to understand the two-process design (FreeCAD + Sidecar).

### Step 2: Trace the Data Flow
Read `02_data_flow.md` to see how a validation request flows through the system.

### Step 3: Deep Dive into Components
- To modify validation rules → `04_validators.md`
- To change AI behavior → `05_ai_integration.md`
- To add new CAD operations → `06_tool_registry.md`
- To modify UI → `08_ui_components.md`

### Step 4: Understand Safety Mechanisms
Read `07_approval_system.md` to understand how human approval is enforced.

---

## 🔑 Key Design Decisions

1. **Two-Process Architecture**: FreeCAD module runs in-process; LangGraph runs in separate sidecar process
2. **JSON Data Exchange**: CAD model is extracted as structured JSON (NOT screenshots/images)
3. **Rule-First Validation**: Deterministic validators run before AI is called
4. **Human-in-the-Loop**: All mutating operations require explicit approval
5. **Undoable Changes**: All modifications wrapped in FreeCAD transactions
6. **Event-Driven UI**: SSE (Server-Sent Events) for real-time AI streaming
7. **Persistent Sessions**: State saved in FreeCAD document objects

---

## 📊 AI Model Configuration

| Model | Provider | Use Case |
|-------|----------|----------|
| `gpt-5.4` | OpenAI | Primary model for validation and copilot |
| `gpt-5.4-pro` | OpenAI | Deep review (slower, on-demand) |
| `gpt-5.4-mini` | OpenAI | Background triage (cheap, fast) |
| `gemini-2.0-flash` | Gemini | Primary model for validation and copilot |
| `gemini-1.5-pro` | Gemini | Deep review (complex reasoning) |
| `gemini-1.5-flash` | Gemini | Background triage (ultra-fast) |

**Provider Selection:** Automatic based on model name prefix (`gemini-*` → Gemini, otherwise → OpenAI)

---

## 🛡️ Safety Features

- ✅ All mutating operations require human approval
- ✅ Changes wrapped in transactions (undoable)
- ✅ Read-only tools auto-execute; mutating tools interrupt
- ✅ LangGraph interrupts for approval and tool results
- ✅ Schema validation on model outputs
- ✅ Graceful degradation on errors (network, API, sidecar)

---

## 📝 Related Documentation

- Main README: `/README.md`
- Architecture Plan: `/plan.md` (root level)
- Test Guide: `/test.md` (root level)

---

*Generated for MagicCAD AI project - FreeCAD-based AI validation and copilot system*
