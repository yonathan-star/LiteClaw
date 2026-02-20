# Roadmap

This roadmap is intentionally strict for alpha. It defines what LiteClaw is prioritizing and what is explicitly out of scope.

## Current Phase

`v0.1.x-alpha` (stabilization and contributor onboarding)

## Near-Term Priorities

1. Reliability hardening
- Improve error handling paths across backend and desktop
- Reduce cross-platform behavior differences
- Expand regression test coverage for policy gates

2. Observability and debugging
- Improve TaskTrace readability in Advanced mode
- Tighten Doctor checks and recommendations
- Improve log redaction and export ergonomics

3. Documentation and contributor flow
- Keep contracts and behavior docs synchronized
- Improve issue triage and alpha feedback loops
- Expand onboarding docs for first-time contributors

## Planned Milestones

## M4 (ShellAgent hardening)
- Keep shell policy read-only and allowlist-first
- Expand deny-pattern coverage and tests
- Improve Windows/macOS/Linux policy consistency

## M5 (Model workflow maturity)
- Improve model registry UX and error handling
- Add clearer model status/reporting in Doctor
- Keep cloud functionality disabled by default

## M6 (Advanced panel polish)
- Improve Tasks/Logs/System Health UI flows
- Add better export ergonomics for bug reports
- Improve trace filtering and navigation

## Explicitly Not Planned for Alpha

- Plugin marketplace
- Background indexing
- Autonomous long-running swarm workflows
- Cloud sync/accounts
- Implicit permissions or silent side effects

## Acceptance Bias

For alpha, maintainability and safety take precedence over feature velocity.
