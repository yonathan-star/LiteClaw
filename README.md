# LiteClaw

Laptop-first, local-first open agent app (desktop + CLI) focused on explicit permissions, deterministic execution flow, and practical safety defaults.

## Status

Alpha (`v0.1.0-alpha` target).  
LiteClaw is under active development. APIs, UI, and internal behavior may change.

Security boundaries and permission guarantees are treated as stable contracts.

## Privacy Promise

- Local-only by default
- No telemetry
- No cloud storage
- No cloud model calls unless explicitly enabled

## Quickstart

1. Start backend:
`cd apps/backend`  
`python -m venv .venv`  
`.venv\Scripts\Activate.ps1` (Windows)  
`pip install -r requirements.txt`  
`$env:LITECLAW_AUTH_TOKEN="<random-token>"`  
`python main.py`

2. Run desktop shell:
`cd apps/desktop`  
`npm install`  
`npm run dev`

## Architecture Overview

LiteClaw has three layers:

1. Desktop App (Tauri)
- Owns local configuration
- Manages backend lifecycle
- Presents UI (Simple + Advanced modes)
- Does not enforce security policy itself

2. Local Backend (FastAPI)
- Authoritative execution engine
- Enforces permissions, approvals, and policy
- Executes file, shell, and model actions
- Persists local state (tasks, logs, models)

3. Contract Layer (Schemas)
- JSON Schemas define Plans, Action Cards, Permission Scopes, Task Traces, and Doctor Reports
- Prevents UI/backend drift
- Acts as a core safety contract

All side effects flow through:
`Plan -> Action Card -> One-Time Approval Token -> Execution`

## Security Model (Explicit)

LiteClaw is designed around these guarantees:

- Local-first by default
- No telemetry
- No background execution
- No implicit permissions
- No command execution without:
1. Structured plan
2. User approval
3. One-time execution token
4. Backend-side enforcement

Shell execution is:

- Disabled by default
- Allowlist-only
- Operator-free (`&&`, `|`, `>`, etc. denied)
- CWD-jail enforced
- Approval-token gated

File access is:

- Scoped to user-approved folders
- Blocked from system paths
- Enforced server-side

This model is enforced even if UI behavior is incorrect or incomplete.

## Repo Layout

- `PRD.md`: product + MVP scope + locked decisions + acceptance criteria
- `SECURITY.md`: threat model and vulnerability reporting policy
- `CONTRIBUTING.md`: contributor setup, standards, and PR checklist
- `ROADMAP.md`: phased priorities and explicit non-goals
- `CODE_OF_CONDUCT.md`: participation and enforcement expectations
- `schemas/`: canonical JSON contracts
- `docs/issues-backlog.md`: epics and tasks mapped to milestones
- `docs/alpha-issues.md`: seeded alpha issue candidates
- `apps/backend/`: FastAPI localhost service with strict bearer-token auth
- `apps/desktop/`: Tauri desktop shell and UI
- `packages/shared/`: destination for generated shared types

## How To Report Bugs

For actionable bug reports, attach these three artifacts:

1. Doctor export
- Advanced -> System Health -> `Run Doctor`
- Export JSON or Markdown

2. TaskTrace export
- Advanced -> Tasks -> open failing task
- Export JSON or Markdown

3. Redacted logs export
- Advanced -> Logs -> enable `Redact paths`
- Export logs and attach output

Include:

- LiteClaw version
- OS and version
- Exact reproduction steps
- Expected behavior vs actual behavior

## Screenshots

- `docs/screenshots/assistant.png` (placeholder)
- `docs/screenshots/action-card.png` (placeholder)
- `docs/screenshots/system-health.png` (placeholder)
