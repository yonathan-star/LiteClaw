import time
from uuid import uuid4

import main
import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"


def authed() -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {TOKEN}"})


def issue_token(client: TestClient, plan_id: str) -> str:
    response = client.post("/v1/approvals/issue-token", json={"plan_id": plan_id})
    assert response.status_code == 200, response.text
    return response.json()["token_id"]


def build_file_search_plan(
    root: str, query: str = "TODO", max_results: int = 10
) -> dict:
    return {
        "plan_id": str(uuid4()),
        "created_at": "2026-02-20T00:00:00Z",
        "user_intent_summary": f"Search for {query}",
        "requires_approval": True,
        "required_permissions": [
            {"type": "file", "mode": "read", "targets": [root]},
        ],
        "steps": [
            {
                "step_id": "s1",
                "agent": "file",
                "action": "file.search",
                "inputs": {
                    "query": query,
                    "root": root,
                    "globs": ["**/*.txt", "**/*.md", "**/*.py"],
                    "max_results": max_results,
                    "max_snippet_chars": 120,
                },
                "side_effects": "none",
                "preview": f"Search for {query}",
            }
        ],
        "estimated_risk": "low",
        "dry_run": True,
        "router_confidence": 0.95,
        "router_fallback_used": False,
        "explain": "Read-only file search",
    }


def build_file_read_plan(allowed_root: str, path: str, max_chars: int = 50) -> dict:
    return {
        "plan_id": str(uuid4()),
        "created_at": "2026-02-20T00:00:00Z",
        "user_intent_summary": "Read file text",
        "requires_approval": True,
        "required_permissions": [
            {"type": "file", "mode": "read", "targets": [allowed_root]},
        ],
        "steps": [
            {
                "step_id": "s1",
                "agent": "file",
                "action": "file.read_text",
                "inputs": {
                    "path": path,
                    "max_chars": max_chars,
                },
                "side_effects": "none",
                "preview": "Read text from file",
            }
        ],
        "estimated_risk": "low",
        "dry_run": True,
        "router_confidence": 0.95,
        "router_fallback_used": False,
        "explain": "Read-only file read",
    }


def test_file_search_returns_limited_results_with_snippets(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    main.current_config = main.AppConfig(allowed_folders=[str(tmp_path.resolve())])
    client = authed()

    for i in range(40):
        text = "TODO: fix this soon" if i % 3 == 0 else "no marker here"
        (tmp_path / f"file_{i}.txt").write_text(text, encoding="utf-8")

    plan = build_file_search_plan(str(tmp_path), query="TODO", max_results=10)
    main.stored_plans[main.UUID(plan["plan_id"])] = main.Plan(**plan)
    token = issue_token(client, plan["plan_id"])

    response = client.post(
        "/v1/tasks/execute",
        json={"plan": plan, "approval_token_id": token},
    )
    assert response.status_code == 200, response.text
    trace = response.json()
    assert trace["status"] == "completed"

    completion_events = [
        event
        for event in trace["events"]
        if event["message"].startswith("search completed in")
    ]
    assert completion_events, "missing search completion event"
    details = completion_events[0]["details"]
    assert 1 <= details["count"] <= 10
    assert all(len(item["snippet"]) <= 120 for item in details["results"])


def test_file_read_text_scope_enforced(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    main.current_config = main.AppConfig(
        allowed_folders=[str((tmp_path / "allowed").resolve())]
    )
    client = authed()

    allowed_root = tmp_path / "allowed"
    disallowed_root = tmp_path / "outside"
    allowed_root.mkdir()
    disallowed_root.mkdir()
    target = disallowed_root / "secret.txt"
    target.write_text("this should not be readable", encoding="utf-8")

    plan = build_file_read_plan(str(allowed_root), str(target), max_chars=20)
    main.stored_plans[main.UUID(plan["plan_id"])] = main.Plan(**plan)
    token = issue_token(client, plan["plan_id"])

    response = client.post(
        "/v1/tasks/execute",
        json={"plan": plan, "approval_token_id": token},
    )
    assert response.status_code == 403, response.text


def test_file_read_text_truncates_to_max_chars(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    main.current_config = main.AppConfig(
        allowed_folders=[str((tmp_path / "allowed").resolve())]
    )
    client = authed()

    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    target = allowed_root / "note.txt"
    target.write_text("A" * 200, encoding="utf-8")

    plan = build_file_read_plan(str(allowed_root), str(target), max_chars=50)
    main.stored_plans[main.UUID(plan["plan_id"])] = main.Plan(**plan)
    token = issue_token(client, plan["plan_id"])

    response = client.post(
        "/v1/tasks/execute",
        json={"plan": plan, "approval_token_id": token},
    )
    assert response.status_code == 200, response.text
    trace = response.json()
    assert trace["status"] == "completed"
    read_event = next(
        event for event in trace["events"] if event["message"] == "file read completed"
    )
    assert read_event["details"]["returned_chars"] == 50
    assert read_event["details"]["truncated"] is True


@pytest.mark.slow
def test_file_search_5000_files_performance(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    main.current_config = main.AppConfig(allowed_folders=[str(tmp_path.resolve())])
    client = authed()

    for i in range(5000):
        content = f"file {i} - regular content"
        if i % 100 == 0:
            content += " TODO marker"
        (tmp_path / f"doc_{i}.txt").write_text(content, encoding="utf-8")

    plan = build_file_search_plan(str(tmp_path), query="TODO", max_results=10)
    main.stored_plans[main.UUID(plan["plan_id"])] = main.Plan(**plan)
    token = issue_token(client, plan["plan_id"])

    started = time.perf_counter()
    response = client.post(
        "/v1/tasks/execute",
        json={"plan": plan, "approval_token_id": token},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200, response.text
    trace = response.json()
    assert trace["status"] == "completed"
    assert elapsed < 20.0, f"search took too long: {elapsed:.2f}s"

    completion_event = next(
        event
        for event in trace["events"]
        if event["message"].startswith("search completed in")
    )
    assert 1 <= completion_event["details"]["count"] <= 10
