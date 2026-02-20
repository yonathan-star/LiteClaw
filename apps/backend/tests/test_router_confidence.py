import main
from fastapi.testclient import TestClient

TOKEN = "test-token"


def authed() -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_ambiguous_prompt_uses_safe_fallback() -> None:
    main.API_TOKEN = TOKEN
    client = authed()
    response = client.post(
        "/v1/router/plan",
        json={"prompt": "Can you maybe help around my files?", "dry_run": True},
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["router_confidence"] < 0.70
    assert plan["router_fallback_used"] is True
    assert plan["steps"][0]["agent"] == "conversation"
    assert plan["steps"][0]["side_effects"] == "none"


def test_clear_file_search_prompt_routes_to_file_agent() -> None:
    main.API_TOKEN = TOKEN
    client = authed()
    response = client.post(
        "/v1/router/plan",
        json={
            "prompt": "Search my project folder for 'TODO' and show top 10 files",
            "allowed_folders": ["."],
            "dry_run": True,
        },
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["router_confidence"] >= 0.70
    assert plan["router_fallback_used"] is False
    assert plan["steps"][0]["agent"] == "file"
    assert plan["steps"][0]["action"] == "file.search"
