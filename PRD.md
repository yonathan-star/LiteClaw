# LiteClaw PRD (v1.0)

Product Requirements Document - Laptop-First Open Agent App  
Status: Draft for GitHub  
Owner: You  
Last Updated: February 20, 2026

## 1) Summary

LiteClaw is an open-source, laptop-optimized AI agent desktop app (and CLI) that runs locally by default using a small local model and tool/agent plugins. LiteClaw stores data locally only (no cloud storage, no telemetry). Cloud model use is optional and off by default.

## 2) Goals

Primary:

- Runs on typical laptops (8-16GB RAM, no GPU required)
- Local-first privacy (no cloud storage, no telemetry by default)
- Install + first task in minutes with sensible defaults
- Hybrid UI (simple assistant + optional advanced controls)
- Extensible agents with stable APIs

Secondary:

- Cross-platform: Windows, macOS, Linux
- Apple Silicon support
- Desktop + CLI parity

## 3) Non-Goals

- Training models
- Distributed multi-machine swarms
- Enterprise SSO/auth
- Always-on full-disk indexing by default
- Cloud sync of sessions/settings

## 4) Locked Decisions (Drift Prevention)

### A. Backend Transport

- Backend uses FastAPI on `127.0.0.1` only.
- Tauri generates and passes a per-launch random auth token to backend.
- Every backend request requires `Authorization: Bearer <token>`.
- No LAN exposure.

### B. Persistence

- Local-only defaults.
- `history_enabled: true` by default (user toggleable).
- Sessions/logs/config stored locally.
- Cloud providers remain disabled/off in MVP (optional stub only).

### C. Safety Enforcement

- Backend is authoritative for all permission checks.
- UI can request approval and display state but cannot bypass backend checks.

## 5) Functional Requirements

- Chat + task interface with explicit approval for side effects
- Local model inference (llama.cpp + GGUF)
- Router that emits structured plans
- Modular agent system with dry-run previews
- Local persistence for settings/sessions/logs/models/plugins
- Optional cloud models (off by default)
- Doctor system check and export
- Session/log export to Markdown/JSON

## 6) Non-Functional Requirements

- Runs on 8GB RAM in Low Resource mode
- Idle CPU remains low after task completion
- Startup under 10s after setup
- No hidden network calls
- Crash-safe local storage with clear errors

## 7) Architecture

- Desktop shell: Tauri
- Backend service: Python FastAPI (localhost + bearer token)
- Inference: llama.cpp (GGUF)
- Storage: local JSON/session/log files

## 8) Contracts (Canonical)

Canonical JSON schemas live in `schemas/`.

### Plan

A deterministic, structured representation of intended work.

Required fields:

- `plan_id` (uuid)
- `created_at` (date-time)
- `user_intent_summary` (string)
- `requires_approval` (bool)
- `required_permissions` (PermissionScope[])
- `steps` (ordered Step[])
- `estimated_risk` (`low|medium|high`)
- `dry_run` (bool, default true)
- `explain` (human-readable explanation)

### Step

Required fields:

- `step_id`
- `agent` (`conversation|file|shell|browser`)
- `action` (e.g. `file.search`, `shell.exec`, `file.write_text`)
- `inputs` (object)
- `outputs_schema` (optional)
- `side_effects` (`none|write|exec|network`)
- `preview` (plain-English preview)

### ActionCard

Generated from a plan when approval is required.

Required fields:

- `card_id`
- `plan_id`
- `title`
- `what_will_happen` (string[])
- `exact_targets` (files/paths/commands/urls)
- `warnings` (string[])
- `approve_token_request` (approval request payload)

### Approval Token

Issued only after explicit user approval.

- Bound to `plan_id`
- TTL: 5 minutes
- One-time use
- Required to execute side-effect steps

## 9) MVP Scope (Locked)

### Included Agents

- ConversationAgent: no side effects
- FileAgent: read/search + optional write with diff preview + approval
- ShellAgent: disabled by default, allowlist + per-command approval + cwd jail

### Excluded from MVP

- Full browser automation/crawling/scraping
- Background indexing
- Plugin marketplace

Research in MVP is limited to user-pasted content or single-URL explicit fetch if enabled.

## 10) UI Requirements (MVP)

### Simple Mode

- Assistant: transcript, composer, Action Card drawer, always-visible Local Only indicator
- Sessions (if history enabled): list, open, delete, export
- Settings: performance profile, model manager, privacy toggles, permissions

### Advanced Mode

- Tasks: task list + trace
- Agents: toggles + status + last run
- Files: allowed folders, write toggle, blocked paths
- System Health: doctor checks + export
- Logs: view + export + redact

## 11) Permission Model

Permissions:

- File read scope
- File write
- Shell execution
- Network fetch (disabled by default in MVP)

Defaults:

- Read-only file access
- Shell off
- Cloud off

Any side effect requires:

1. Plan with declared side effects
2. Action Card approval
3. Backend-issued short-lived one-time approval token

## 12) Local Storage

```
config.json
sessions/
logs/
models/
plugins/
```

Example config:

```json
{
  "ui_mode": "simple",
  "privacy": {
    "local_only": true,
    "cloud_enabled": false,
    "history_enabled": true
  },
  "allowed_folders": [],
  "shell": {
    "enabled": false,
    "allowlist": []
  },
  "performance_profile": "balanced",
  "default_model_id": ""
}
```

## 13) Acceptance Criteria (MVP Hard Gates)

- Fresh install to first successful task in under 5 minutes.
- Low Resource mode on 8GB RAM machine completes 10 prompts in sequence without crash.
- File search over 5,000 text files completes within 45s on SSD baseline hardware.
- Idle CPU returns to low usage after response completion (no sustained busy loop).
- Shell commands enforce deterministic timeout and output truncation.
- All file writes show diff preview and require valid approval token.
- No cloud requests unless user explicitly enables cloud.
- Doctor report correctly reflects model/backend/system status.

## 14) Open-Source Packaging

Required top-level files:

- `README.md`
- `LICENSE` (MIT or Apache-2.0)
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `ROADMAP.md`

## 15) Engineering MVP Checklist

- Tauri app skeleton + tray
- Python backend service (FastAPI)
- Local config/session/log storage
- llama.cpp integration
- Router plan generation
- Action Card approval flow
- FileAgent read/search + diff writes
- ShellAgent allowlist + execution guardrails
- Doctor report
- Session/log export
- Windows/macOS/Linux packaging
