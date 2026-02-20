# LiteClaw MVP Backlog

This backlog is structured as Epics -> Issues and mapped to milestone targets.

## Milestones

- M1: Foundation (Week 1-2)
- M2: Router + Approvals (Week 3)
- M3: File Agent (Week 4)
- M4: Shell Agent (Week 5)
- M5: Local Model (Week 6)
- M6: Advanced Panels + Doctor + Export (Week 7)
- M7: Packaging + Hardening (Week 8)

## Epic 1: Monorepo + Contracts (M1)

- [ ] Initialize repo layout: `apps/desktop`, `apps/backend`, `packages/shared`, `schemas`, `docs`
- [ ] Add and validate canonical JSON schemas in `schemas/`
- [ ] Generate shared types from schemas for TS/Python
- [ ] Add top-level governance files: `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `ROADMAP.md`, `CODE_OF_CONDUCT.md`

## Epic 2: Backend Runtime + Auth (M1)

- [ ] Create FastAPI service bound to `127.0.0.1`
- [ ] Add per-launch bearer token auth middleware
- [ ] Add health endpoint and version handshake endpoint
- [ ] Add structured logging with local file sink and rotation

## Epic 3: Desktop Shell + Bridge (M1-M2)

- [ ] Bootstrap Tauri + UI app shell
- [ ] Launch backend process from desktop app
- [ ] Implement API client with auth token injection
- [ ] Add startup error states and recovery UI

## Epic 4: Router + Plan Contracts (M2)

- [ ] Implement deterministic router for: conversation, file, shell, multi-step
- [ ] Return `Plan` object for every prompt
- [ ] Compute `required_permissions` and `estimated_risk`
- [ ] Add dry-run by default (`dry_run=true`)
- [ ] Unit tests for router classification and plan structure

## Epic 5: Approval Flow (M2)

- [ ] Build Action Card backend generator from Plan
- [ ] Build Action Card UI drawer in Assistant screen
- [ ] Implement approval endpoint issuing one-time 5-minute token
- [ ] Enforce token validation on all side-effect execution paths
- [ ] Add denial and timeout handling paths

## Epic 6: Conversation Agent (M2)

- [ ] Implement ConversationAgent (no side effects)
- [ ] Ensure output is pure response/plan without system mutation
- [ ] Add tests proving side-effect prohibition

## Epic 7: File Agent (M3)

- [ ] Implement folder-scoped read/search APIs
- [ ] Add blocked path defaults (system-sensitive paths)
- [ ] Implement write flow with diff preview payload
- [ ] Require approval token for writes
- [ ] Add performance test for search over 5k files

## Epic 8: Shell Agent (M4)

- [ ] Implement shell toggle default off
- [ ] Implement command allowlist
- [ ] Enforce cwd jail to approved project folder
- [ ] Add timeout and output truncation limits
- [ ] Add dangerous pattern deny rules
- [ ] Require approval token per execution

## Epic 9: Local Model Integration (M5)

- [ ] Integrate llama.cpp runner
- [ ] Add performance profiles: `low`, `balanced`, `high_reasoning`
- [ ] Add model registry and default model setting
- [ ] Add first-run model download consent flow

## Epic 10: UI Screens (M5-M6)

- [ ] Simple Mode: Assistant screen with Action Card drawer + Local Only badge
- [ ] Simple Mode: Sessions list/open/delete/export
- [ ] Simple Mode: Settings for performance/privacy/permissions/models
- [ ] Advanced Mode: Tasks list + trace viewer
- [ ] Advanced Mode: Agents status/toggles
- [ ] Advanced Mode: Files scope/write/blocked paths
- [ ] Advanced Mode: Logs viewer + redact + export

## Epic 11: Doctor + Export (M6)

- [ ] Implement doctor checks: CPU/RAM/disk/model/backend/permissions
- [ ] Produce `DoctorReport` contract output
- [ ] Export doctor report to JSON/Markdown
- [ ] Export sessions/logs to Markdown/JSON

## Epic 12: Acceptance + Packaging (M7)

- [ ] Add end-to-end first-run test (<5 minutes to first task)
- [ ] Add low-resource stability test: 10 prompts on 8GB profile
- [ ] Add idle CPU regression check (no busy loop)
- [ ] Add cross-platform packaging workflow (Windows/macOS/Linux)
- [ ] Add release checklist and artifact signing notes
