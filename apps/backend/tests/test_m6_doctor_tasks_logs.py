import json
from pathlib import Path

import main
from fastapi.testclient import TestClient

TOKEN = "test-token"


def authed() -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_doctor_report_contract(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    previous_data_dir = main.DATA_DIR
    try:
        main.DATA_DIR = tmp_path
        main.reload_config()
        main.reload_models()
        client = authed()
        response = client.get("/v1/doctor/report")
        assert response.status_code == 200, response.text
        report = response.json()
        required = {
            "cpu",
            "ram",
            "disk",
            "model_installed",
            "model_loadable",
            "backend_health",
            "permissions_config",
        }
        names = {item["name"] for item in report["checks"]}
        assert required.issubset(names)
        assert report["overall_status"] in {"ok", "warn", "fail"}
    finally:
        main.DATA_DIR = previous_data_dir


def test_task_persistence_and_lookup(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    previous_data_dir = main.DATA_DIR
    try:
        main.DATA_DIR = tmp_path
        main.reload_config()
        main.current_config = main.AppConfig(allowed_folders=[str(tmp_path.resolve())])
        main.approval_tokens.clear()
        main.stored_plans.clear()
        client = authed()

        plan_response = client.post(
            "/v1/router/plan",
            json={
                "prompt": "search my project folder for TODO and list 10 results",
                "allowed_folders": [str(tmp_path.resolve())],
                "dry_run": True,
            },
        )
        assert plan_response.status_code == 200
        plan = plan_response.json()

        token = client.post(
            "/v1/approvals/issue-token", json={"plan_id": plan["plan_id"]}
        ).json()["token_id"]

        execute = client.post(
            "/v1/tasks/execute",
            json={"plan": plan, "approval_token_id": token},
        )
        assert execute.status_code == 200, execute.text
        trace = execute.json()

        listed = client.get("/v1/tasks")
        assert listed.status_code == 200
        assert any(item["task_id"] == trace["task_id"] for item in listed.json())

        fetched = client.get(f"/v1/tasks/{trace['task_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["task_id"] == trace["task_id"]
    finally:
        main.DATA_DIR = previous_data_dir


def test_logs_export_redacts_paths(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    previous_data_dir = main.DATA_DIR
    try:
        main.DATA_DIR = tmp_path
        main.reload_config()
        allowed = tmp_path / "allowed"
        allowed.mkdir(parents=True, exist_ok=True)
        main.current_config = main.AppConfig(allowed_folders=[str(allowed.resolve())])

        log_file = main.backend_log_path()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        raw_line = f"path {allowed.resolve()} data_dir {tmp_path.resolve()}"
        log_file.write_text(raw_line + "\n", encoding="utf-8")

        client = authed()
        response = client.post(
            "/v1/logs/export",
            json={"redact_paths": True, "format": "txt"},
        )
        assert response.status_code == 200, response.text
        content = response.json()["content"]
        assert str(allowed.resolve()) not in content
        assert str(tmp_path.resolve()) not in content
        assert "{{ALLOWED_FOLDER_1}}" in content or "{{DATA_DIR}}" in content
        assert "{{DATA_DIR}}" in content
    finally:
        main.DATA_DIR = previous_data_dir
