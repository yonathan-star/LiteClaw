from pathlib import Path
from uuid import uuid4

import main
from fastapi.testclient import TestClient

TOKEN = "test-token"


def authed() -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {TOKEN}"})


def create_search_plan(client: TestClient) -> dict:
    response = client.post(
        "/v1/router/plan",
        json={
            "prompt": "search my project folder for TODO and list 10 results",
            "allowed_folders": ["."],
            "dry_run": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def issue_token(client: TestClient, plan_id: str) -> dict:
    response = client.post("/v1/approvals/issue-token", json={"plan_id": plan_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_token_one_time_use() -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    main.current_config = main.AppConfig(allowed_folders=[str(Path(".").resolve())])
    client = authed()

    plan = create_search_plan(client)
    token = issue_token(client, plan["plan_id"])

    first = client.post(
        "/v1/tasks/execute",
        json={"plan": plan, "approval_token_id": token["token_id"]},
    )
    assert first.status_code == 200, first.text
    assert first.json().get("status") == "completed"

    second = client.post(
        "/v1/tasks/execute",
        json={"plan": plan, "approval_token_id": token["token_id"]},
    )
    assert second.status_code == 403, second.text


def test_dry_run_blocks_side_effects_even_with_token() -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    main.current_config = main.AppConfig(allowed_folders=[str(Path(".").resolve())])
    client = authed()

    plan = {
        "plan_id": str(uuid4()),
        "created_at": "2026-02-20T00:00:00Z",
        "user_intent_summary": "Write a file",
        "requires_approval": True,
        "required_permissions": [
            {"type": "file", "mode": "write", "targets": ["C:/tmp"]}
        ],
        "steps": [
            {
                "step_id": "s1",
                "agent": "file",
                "action": "file.write_text",
                "inputs": {"path": "C:/tmp/demo.txt", "content": "hello"},
                "side_effects": "write",
                "preview": "Write text to file",
            }
        ],
        "estimated_risk": "medium",
        "dry_run": True,
        "router_confidence": 0.95,
        "router_fallback_used": False,
        "explain": "Attempt write in dry run",
    }

    main.stored_plans[main.UUID(plan["plan_id"])] = main.Plan(**plan)
    token = issue_token(client, plan["plan_id"])

    response = client.post(
        "/v1/tasks/execute",
        json={"plan": plan, "approval_token_id": token["token_id"]},
    )
    assert response.status_code == 403, response.text
