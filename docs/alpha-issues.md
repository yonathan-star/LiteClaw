# Alpha Seed Issues

Use these as initial GitHub issues for contributor onboarding and alpha feedback.

## good first issue

1. Improve TaskTrace event formatting in Advanced Tasks panel
- Label: `good first issue`
- Scope: UI-only polish in `apps/desktop/src/main.js`
- Acceptance: Event rows remain chronological and readable with long details

2. Add backend unit tests for doctor check recommendations
- Label: `good first issue`
- Scope: tests in `apps/backend/tests/`
- Acceptance: verify recommendation strings for each non-`ok` check path

## alpha feedback

3. Collect platform-specific shell policy feedback (Windows/macOS/Linux)
- Label: `alpha feedback`
- Scope: document mismatches and expected vs actual policy behavior
- Acceptance: report includes reproducible commands and exported artifacts

4. Evaluate log redaction quality on real user paths
- Label: `alpha feedback`
- Scope: test logs export with deep nested allowed folders
- Acceptance: no absolute data dir or allowed folder leaks in redacted export

## docs

5. Add architecture diagram to README
- Label: `docs`
- Scope: static diagram + concise callouts for plan/action/token flow
- Acceptance: diagram matches implemented backend flow

## UX polish

6. Improve empty states for Advanced panels (Tasks/Logs/System Health)
- Label: `help wanted`, `UX polish`
- Scope: clear actionable empty-state copy and retry affordances
- Acceptance: no blank panels on fresh install

## security

7. Add regression tests for shell deny-pattern coverage
- Label: `security`, `help wanted`
- Scope: extend `apps/backend/tests/test_shell_agent.py`
- Acceptance: new deny-patterns fail with deterministic 403 reasons

8. Add tests for config reload race handling
- Label: `security`
- Scope: backend config reload path consistency under repeated calls
- Acceptance: no stale config usage across subsequent executions
