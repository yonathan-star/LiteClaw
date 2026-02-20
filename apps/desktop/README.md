# LiteClaw Desktop (MVP Skeleton)

Minimal Tauri shell that:

- starts backend process (`apps/backend/main.py`)
- sets a per-launch API token
- exposes token/base URL to frontend via Tauri command
- runs Day 1 flow from Assistant screen

## Run (after Rust + Node + Tauri prerequisites)

```powershell
cd apps/desktop
npm install
npm run dev
```

The UI includes a `Run Demo Flow` button for:

1. `POST /v1/router/plan`
2. Action card rendering (frontend)
3. `POST /v1/approvals/issue-token`
4. `POST /v1/tasks/execute`
