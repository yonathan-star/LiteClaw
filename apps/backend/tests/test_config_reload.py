import json
from uuid import uuid4

import main
from fastapi.testclient import TestClient

TOKEN = "test-token"


def authed() -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {TOKEN}"})


def build_search_plan(root: str) -> dict:
    return {
        "plan_id": str(uuid4()),
        "created_at": "2026-02-20T00:00:00Z",
        "user_intent_summary": "Search",
        "requires_approval": True,
        "required_permissions": [{"type": "file", "mode": "read", "targets": [root]}],
        "steps": [
            {
                "step_id": "s1",
                "agent": "file",
                "action": "file.search",
                "inputs": {
                    "query": "TODO",
                    "root": root,
                    "globs": ["**/*.txt"],
                    "max_results": 5,
                    "max_snippet_chars": 120,
                },
                "side_effects": "none",
                "preview": "search",
            }
        ],
        "estimated_risk": "low",
        "dry_run": True,
        "router_confidence": 0.95,
        "router_fallback_used": False,
        "explain": "search test",
    }


def test_config_reload_allows_search_after_folder_added(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    previous_data_dir = main.DATA_DIR
    try:
        main.DATA_DIR = tmp_path
        main.reload_config()
        client = authed()

        root = tmp_path / "project"
        root.mkdir()
        (root / "a.txt").write_text("TODO in file", encoding="utf-8")
        plan = build_search_plan(str(root))
        main.stored_plans[main.UUID(plan["plan_id"])] = main.Plan(**plan)

        token_response = client.post(
            "/v1/approvals/issue-token", json={"plan_id": plan["plan_id"]}
        )
        assert token_response.status_code == 200
        token = token_response.json()["token_id"]

        first = client.post(
            "/v1/tasks/execute", json={"plan": plan, "approval_token_id": token}
        )
        assert first.status_code == 403

        cfg_path = tmp_path / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["allowed_folders"] = [str(root.resolve())]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        reload_response = client.post("/v1/config/reload")
        assert reload_response.status_code == 200
        assert str(root.resolve()) in reload_response.json()["allowed_folders"]

        token_response2 = client.post(
            "/v1/approvals/issue-token", json={"plan_id": plan["plan_id"]}
        )
        token2 = token_response2.json()["token_id"]
        second = client.post(
            "/v1/tasks/execute", json={"plan": plan, "approval_token_id": token2}
        )
        assert second.status_code == 200, second.text
    finally:
        main.DATA_DIR = previous_data_dir
