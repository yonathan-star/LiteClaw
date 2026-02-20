import shutil
from pathlib import Path
from uuid import uuid4

import main
from fastapi.testclient import TestClient

TOKEN = "test-token"


def authed() -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {TOKEN}"})


def build_shell_plan(
    command: str,
    cwd: str,
    *,
    timeout_ms: int = 10_000,
    max_output_chars: int = 20_000,
    plan_roots: list[str] | None = None,
) -> dict:
    roots = plan_roots or [cwd]
    return {
        "plan_id": str(uuid4()),
        "created_at": "2026-02-20T00:00:00Z",
        "user_intent_summary": f"Run {command}",
        "requires_approval": True,
        "required_permissions": [
            {"type": "file", "mode": "read", "targets": roots},
            {"type": "shell", "mode": "exec", "targets": [command]},
        ],
        "steps": [
            {
                "step_id": "s1",
                "agent": "shell",
                "action": "shell.exec",
                "inputs": {
                    "command": command,
                    "cwd": cwd,
                    "timeout_ms": timeout_ms,
                    "max_output_chars": max_output_chars,
                },
                "side_effects": "exec",
                "preview": f"Run {command}",
            }
        ],
        "estimated_risk": "medium",
        "dry_run": False,
        "router_confidence": 0.95,
        "router_fallback_used": False,
        "explain": "Shell execution test",
    }


def issue_token(client: TestClient, plan_id: str) -> str:
    response = client.post("/v1/approvals/issue-token", json={"plan_id": plan_id})
    assert response.status_code == 200, response.text
    return response.json()["token_id"]


def execute(client: TestClient, plan: dict, token: str | None) -> TestClient:
    payload = {"plan": plan}
    if token:
        payload["approval_token_id"] = token
    return client.post("/v1/tasks/execute", json=payload)


def configure(tmp_path, shell_enabled: bool = True) -> None:
    main.current_config = main.AppConfig(
        allowed_folders=[str(tmp_path.resolve())],
        shell=main.ShellConfig(enabled=shell_enabled),
    )


def register_plan(plan: dict) -> None:
    main.stored_plans[main.UUID(plan["plan_id"])] = main.Plan(**plan)


def test_shell_disabled_returns_403(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    configure(tmp_path, shell_enabled=False)
    client = authed()
    plan = build_shell_plan("pwd", str(tmp_path))
    register_plan(plan)
    token = issue_token(client, plan["plan_id"])
    response = execute(client, plan, token)
    assert response.status_code == 403


def test_shell_missing_token_returns_403(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    configure(tmp_path, shell_enabled=True)
    client = authed()
    plan = build_shell_plan("pwd", str(tmp_path))
    register_plan(plan)
    response = execute(client, plan, None)
    assert response.status_code == 403


def test_shell_token_reuse_returns_403(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    configure(tmp_path, shell_enabled=True)
    client = authed()
    plan = build_shell_plan("pwd", str(tmp_path))
    register_plan(plan)
    token = issue_token(client, plan["plan_id"])
    first = execute(client, plan, token)
    assert first.status_code == 200, first.text
    second = execute(client, plan, token)
    assert second.status_code == 403


def test_shell_cwd_scope_enforced(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    configure(allowed, shell_enabled=True)
    client = authed()
    plan = build_shell_plan("pwd", str(outside), plan_roots=[str(allowed)])
    register_plan(plan)
    token = issue_token(client, plan["plan_id"])
    response = execute(client, plan, token)
    assert response.status_code == 403


def test_shell_allowlist_and_deny_patterns(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    configure(tmp_path, shell_enabled=True)
    client = authed()

    allowed_plan = build_shell_plan("python --version", str(tmp_path))
    register_plan(allowed_plan)
    token = issue_token(client, allowed_plan["plan_id"])
    allowed_resp = execute(client, allowed_plan, token)
    assert allowed_resp.status_code == 200

    if shutil.which("git"):
        git_plan = build_shell_plan("git status", str(tmp_path))
        register_plan(git_plan)
        token = issue_token(client, git_plan["plan_id"])
        git_resp = execute(client, git_plan, token)
        assert git_resp.status_code == 200

    denied = [
        "git commit",
        "python -m pip install requests",
        "whoami",
        "ls && whoami",
        "ls | grep x",
        "ls > out.txt",
    ]
    for cmd in denied:
        plan = build_shell_plan(cmd, str(tmp_path))
        register_plan(plan)
        token = issue_token(client, plan["plan_id"])
        response = execute(client, plan, token)
        assert response.status_code == 403, f"expected deny for: {cmd}"


def test_internal_commands_work(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    configure(tmp_path, shell_enabled=True)
    sample = tmp_path / "sample.txt"
    sample.write_text("hello\nTODO line\n", encoding="utf-8")
    client = authed()

    commands = [
        "pwd",
        "ls",
        f"cat {sample.name}",
        f"grep TODO {sample.name}",
        f"find . *.txt",
    ]
    for cmd in commands:
        plan = build_shell_plan(cmd, str(tmp_path))
        register_plan(plan)
        token = issue_token(client, plan["plan_id"])
        response = execute(client, plan, token)
        assert response.status_code == 200, (
            f"unexpected status for {cmd}: {response.text}"
        )
        trace = response.json()
        assert trace["status"] in {"completed", "timeout"}


def test_shell_timeout_enforced(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    configure(tmp_path, shell_enabled=True)
    nested = tmp_path / "nested"
    nested.mkdir()
    for i in range(3000):
        (nested / f"f_{i}.txt").write_text("x", encoding="utf-8")
    client = authed()
    plan = build_shell_plan("find . *.txt", str(tmp_path), timeout_ms=1)
    register_plan(plan)
    token = issue_token(client, plan["plan_id"])
    response = execute(client, plan, token)
    assert response.status_code == 200
    assert response.json()["status"] == "timeout"


def test_shell_output_truncation(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    main.approval_tokens.clear()
    main.stored_plans.clear()
    configure(tmp_path, shell_enabled=True)
    large = tmp_path / "large.txt"
    large.write_text("A" * 5000, encoding="utf-8")
    client = authed()
    plan = build_shell_plan(f"cat {large.name}", str(tmp_path), max_output_chars=200)
    register_plan(plan)
    token = issue_token(client, plan["plan_id"])
    response = execute(client, plan, token)
    assert response.status_code == 200
    trace = response.json()
    warn_events = [
        event
        for event in trace["events"]
        if event["message"] == "shell output truncated"
    ]
    assert warn_events, "expected truncation warning event"
