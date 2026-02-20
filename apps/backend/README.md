# LiteClaw Backend (MVP)

FastAPI service bound to localhost with bearer-token auth on all `/v1/*` endpoints.

## Run

```powershell
cd apps/backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:LITECLAW_AUTH_TOKEN = "replace-with-random-token"
$env:LITECLAW_DATA_DIR = "$pwd\\.liteclaw-data"
$env:LITECLAW_PORT = "8765"
python main.py
```

Default URL: `http://127.0.0.1:8765`

## Implemented Endpoints

- `GET /v1/health`
- `GET /v1/version`
- `GET /v1/config`
- `GET /v1/models`
- `GET /v1/doctor/report`
- `GET /v1/doctor/report/export?format=md|json`
- `GET /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/export?format=md|json`
- `GET /v1/logs/tail?lines=200`
- `GET /v1/logs/search?q=...&limit=200`
- `POST /v1/router/plan`
- `POST /v1/config/reload`
- `POST /v1/models/download`
- `POST /v1/models/set-default`
- `POST /v1/logs/export`
- `POST /v1/approvals/action-card`
- `POST /v1/approvals/issue-token`
- `POST /v1/tasks/execute`

All require:

`Authorization: Bearer <LITECLAW_AUTH_TOKEN>`
