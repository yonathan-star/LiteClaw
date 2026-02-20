# Contributing to LiteClaw

Thanks for contributing.

LiteClaw is a security-sensitive, local-first agent runtime. Contributions are welcome, but must preserve security boundaries and contract stability.

## Development Setup

Backend:

```bash
cd apps/backend
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

Desktop:

```bash
cd apps/desktop
npm install
npm run tauri dev
```

Rust toolchain is required for Tauri builds.

## CI Rules

All PRs must:

- Pass backend tests
- Pass schema validation
- Pass desktop build smoke checks on Windows/macOS/Linux
- Not weaken security guarantees

CI is authoritative.

## Contribution Guidelines

Do:

- Add tests for behavior changes
- Keep changes explicit and minimal
- Respect schema contracts
- Treat backend as the security boundary

Do not:

- Add implicit permissions
- Add shell passthrough
- Add unapproved network access
- Add background execution
- Bypass approval-token flow
- Store/transmit user data externally

## Pull Request Checklist

- Tests added or updated
- No security regression
- No schema drift
- Cross-platform behavior considered
- Clear commit message

## Issue Labels

- `good first issue`
- `help wanted`
- `security`
- `alpha feedback`
