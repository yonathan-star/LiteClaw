from uuid import uuid4

import main
from fastapi.testclient import TestClient


def _valid_plan_payload() -> dict:
    return {
        "plan": {
            "plan_id": str(uuid4()),
            "created_at": "2026-02-20T00:00:00Z",
            "user_intent_summary": "Answer directly",
            "requires_approval": False,
            "required_permissions": [],
            "steps": [
                {
                    "step_id": "step-1",
                    "agent": "conversation",
                    "action": "conversation.respond",
                    "inputs": {"prompt": "hello"},
                    "side_effects": "none",
                    "preview": "Generate a direct response",
                }
            ],
            "estimated_risk": "low",
            "dry_run": True,
            "router_confidence": 0.9,
            "router_fallback_used": False,
            "explain": "No side effects",
        }
    }


def test_all_v1_routes_require_auth() -> None:
    client = TestClient(main.app)

    requests = [
        ("GET", "/v1/health", None),
        ("GET", "/v1/version", None),
        ("GET", "/v1/config", None),
        ("GET", "/v1/models", None),
        ("GET", "/v1/doctor/report", None),
        ("GET", "/v1/doctor/report/export", None),
        ("GET", "/v1/tasks", None),
        ("GET", f"/v1/tasks/{uuid4()}", None),
        ("GET", f"/v1/tasks/{uuid4()}/export", None),
        ("GET", "/v1/logs/tail", None),
        ("GET", "/v1/logs/search?q=test", None),
        ("POST", "/v1/config/reload", None),
        ("POST", "/v1/models/download", {"model_id": "test-model"}),
        ("POST", "/v1/models/set-default", {"model_id": "test-model"}),
        ("POST", "/v1/logs/export", {"redact_paths": True, "format": "txt"}),
        ("POST", "/v1/router/plan", {"prompt": "hello"}),
        ("POST", "/v1/approvals/action-card", {"plan_id": str(uuid4())}),
        ("POST", "/v1/approvals/issue-token", {"plan_id": str(uuid4())}),
        ("POST", "/v1/tasks/execute", _valid_plan_payload()),
    ]

    for method, path, payload in requests:
        if method == "GET":
            response = client.get(path)
        else:
            if payload is None:
                response = client.post(path)
            else:
                response = client.post(path, json=payload)
        assert response.status_code == 401, (
            f"{method} {path} should be 401 without auth, got {response.status_code}"
        )
