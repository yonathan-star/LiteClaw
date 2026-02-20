from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_VERSION = "0.1.0-mvp"
ROUTER_CONFIDENCE_THRESHOLD = 0.70
SHELL_CONFIDENCE_THRESHOLD = 0.80
DEFAULT_SHELL_TIMEOUT_MS = 10_000
DEFAULT_SHELL_MAX_OUTPUT_CHARS = 20_000
API_TOKEN = os.environ.get("LITECLAW_AUTH_TOKEN") or os.environ.get(
    "LITECLAW_API_TOKEN", uuid4().hex
)
DATA_DIR = Path(os.environ.get("LITECLAW_DATA_DIR", str(Path.cwd() / ".liteclaw-data")))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class PermissionScope(BaseModel):
    type: Literal["file", "shell", "network", "cloud"]
    mode: Literal["read", "write", "exec", "fetch"]
    targets: list[str]
    reason: str | None = None


class Step(BaseModel):
    step_id: str
    agent: Literal["conversation", "file", "shell", "browser"]
    action: str
    inputs: dict[str, Any]
    outputs_schema: dict[str, Any] | None = None
    side_effects: Literal["none", "write", "exec", "network"]
    preview: str


class Plan(BaseModel):
    plan_id: UUID
    created_at: str
    user_intent_summary: str
    requires_approval: bool
    required_permissions: list[PermissionScope]
    steps: list[Step]
    estimated_risk: Literal["low", "medium", "high"]
    dry_run: bool = True
    router_confidence: float = Field(ge=0.0, le=1.0)
    router_fallback_used: bool
    explain: str


class RouterPlanRequest(BaseModel):
    prompt: str = Field(min_length=1)
    allowed_folders: list[str] = Field(default_factory=list)
    dry_run: bool = True


class IssueTokenRequest(BaseModel):
    plan_id: UUID


class ActionCardRequest(BaseModel):
    plan_id: UUID


class ApprovalToken(BaseModel):
    token_id: UUID
    plan_id: UUID
    issued_at: str
    expires_at: str
    ttl_seconds: int = 300
    one_time_use: bool = True
    consumed_at: str | None = None


class TaskEvent(BaseModel):
    timestamp: str
    level: Literal["debug", "info", "warn", "error"]
    step_id: str | None = None
    message: str
    details: dict[str, Any] | None = None


class TaskTrace(BaseModel):
    task_id: UUID
    plan_id: UUID
    status: Literal["queued", "running", "completed", "failed", "denied", "timeout"]
    started_at: str
    ended_at: str | None = None
    agent: Literal["conversation", "file", "shell", "browser"] | None = None
    events: list[TaskEvent]
    error: str | None = None


class TaskSummary(BaseModel):
    task_id: UUID
    plan_id: UUID
    status: Literal["queued", "running", "completed", "failed", "denied", "timeout"]
    started_at: str
    ended_at: str | None = None
    agent: Literal["conversation", "file", "shell", "browser"] | None = None


class DoctorCheck(BaseModel):
    name: Literal[
        "cpu",
        "ram",
        "disk",
        "model_installed",
        "model_loadable",
        "backend_health",
        "permissions_config",
    ]
    status: Literal["ok", "warn", "fail"]
    details: str
    metrics: dict[str, Any] | None = None
    recommendation: str | None = None


class DoctorReport(BaseModel):
    report_id: UUID
    generated_at: str
    overall_status: Literal["ok", "warn", "fail"]
    checks: list[DoctorCheck]
    summary: str | None = None


class ExecuteTaskRequest(BaseModel):
    plan: Plan
    approval_token_id: UUID | None = None


class ShellConfig(BaseModel):
    enabled: bool = False


class AppConfig(BaseModel):
    allowed_folders: list[str] = Field(default_factory=list)
    shell: ShellConfig = Field(default_factory=ShellConfig)
    history_enabled: bool = True


class ModelEntry(BaseModel):
    model_id: str
    display_name: str
    local_path: str | None = None
    status: Literal["registered", "download_stubbed"] = "registered"


class ModelsState(BaseModel):
    installed_models: list[ModelEntry] = Field(default_factory=list)
    default_model_id: str | None = None


class ModelDownloadRequest(BaseModel):
    model_id: str = Field(min_length=1)
    display_name: str | None = None
    local_path: str | None = None


class ModelSetDefaultRequest(BaseModel):
    model_id: str = Field(min_length=1)


class LogsTailResponse(BaseModel):
    lines: list[str]


class LogsSearchResponse(BaseModel):
    matches: list[str]


class LogsExportRequest(BaseModel):
    redact_paths: bool = True
    format: Literal["txt", "jsonl"] = "txt"


class LogsExportResponse(BaseModel):
    format: Literal["txt", "jsonl"]
    content: str


class ActionCardApproveTokenRequestPayload(BaseModel):
    plan_id: UUID


class ActionCardApproveTokenRequest(BaseModel):
    endpoint: str = "/v1/approvals/issue-token"
    method: str = "POST"
    payload: ActionCardApproveTokenRequestPayload


class ActionCardTargets(BaseModel):
    files: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class ActionCard(BaseModel):
    card_id: UUID
    plan_id: UUID
    title: str
    what_will_happen: list[str]
    exact_targets: ActionCardTargets
    warnings: list[str]
    approve_token_request: ActionCardApproveTokenRequest


approval_tokens: dict[UUID, ApprovalToken] = {}
stored_plans: dict[UUID, Plan] = {}
approval_lock = threading.Lock()
config_lock = threading.Lock()
current_config = AppConfig()
models_lock = threading.Lock()
current_models = ModelsState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    reload_config()
    reload_models()
    ensure_task_store()
    backend_log_path().parent.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="LiteClaw Backend", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


def config_path() -> Path:
    return DATA_DIR / "config.json"


def models_registry_path() -> Path:
    return DATA_DIR / "models" / "registry.json"


def task_dir() -> Path:
    return DATA_DIR / "sessions" / "tasks"


def task_index_path() -> Path:
    return task_dir() / "index.json"


def backend_log_path() -> Path:
    return DATA_DIR / "logs" / "backend.log"


def write_default_config_if_missing() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = config_path()
    if path.exists():
        return
    default = AppConfig().model_dump()
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(default, indent=2), encoding="utf-8")
    temp_path.replace(path)


def ensure_task_store() -> None:
    directory = task_dir()
    directory.mkdir(parents=True, exist_ok=True)
    index = task_index_path()
    if not index.exists():
        index.write_text("[]", encoding="utf-8")


def load_task_index() -> list[TaskSummary]:
    ensure_task_store()
    try:
        payload = json.loads(task_index_path().read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Invalid task index JSON: {exc}"
        ) from exc
    return [TaskSummary(**item) for item in payload]


def write_task_index(entries: list[TaskSummary]) -> None:
    ensure_task_store()
    temp = task_index_path().with_suffix(".tmp")
    temp.write_text(
        json.dumps([entry.model_dump(mode="json") for entry in entries], indent=2),
        encoding="utf-8",
    )
    temp.replace(task_index_path())


def task_trace_path(task_id: UUID) -> Path:
    return task_dir() / f"{task_id}.json"


def persist_task_trace(trace: TaskTrace) -> None:
    ensure_task_store()
    trace_file = task_trace_path(trace.task_id)
    temp = trace_file.with_suffix(".tmp")
    temp.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(trace_file)

    entries = [entry for entry in load_task_index() if entry.task_id != trace.task_id]
    entries.append(
        TaskSummary(
            task_id=trace.task_id,
            plan_id=trace.plan_id,
            status=trace.status,
            started_at=trace.started_at,
            ended_at=trace.ended_at,
            agent=trace.agent,
        )
    )
    entries.sort(key=lambda item: item.started_at, reverse=True)
    write_task_index(entries)


def load_task_trace(task_id: UUID) -> TaskTrace:
    path = task_trace_path(task_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Invalid task trace JSON: {exc}"
        ) from exc
    return TaskTrace(**payload)


def append_backend_log(level: str, message: str) -> None:
    path = backend_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{iso(now_utc())} [{level.upper()}] {message}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def write_models_state(state: ModelsState) -> None:
    path = models_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def load_models_from_disk() -> ModelsState:
    path = models_registry_path()
    if not path.exists():
        state = ModelsState()
        write_models_state(state)
        return state
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Invalid models registry JSON: {exc}"
        ) from exc
    return ModelsState(**raw)


def get_models_snapshot() -> ModelsState:
    with models_lock:
        return current_models.model_copy(deep=True)


def reload_models() -> ModelsState:
    models = load_models_from_disk()
    with models_lock:
        global current_models
        current_models = models
    return models


def load_config_from_disk() -> AppConfig:
    write_default_config_if_missing()
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Invalid config JSON: {exc}"
        ) from exc
    return AppConfig(**raw)


def get_config_snapshot() -> AppConfig:
    with config_lock:
        return current_config.model_copy(deep=True)


def reload_config() -> AppConfig:
    config = load_config_from_disk()
    with config_lock:
        global current_config
        current_config = config
    return config


def generate_doctor_report() -> DoctorReport:
    checks: list[DoctorCheck] = []
    config = get_config_snapshot()
    models = get_models_snapshot()
    now = now_utc()

    checks.append(
        DoctorCheck(
            name="cpu",
            status="ok",
            details=f"CPU cores detected: {os.cpu_count() or 1}.",
            metrics={"cpu_count": os.cpu_count() or 1},
        )
    )

    ram_status: Literal["ok", "warn", "fail"] = "warn"
    ram_details = "Could not determine RAM precisely in this environment."
    ram_metrics: dict[str, Any] | None = None
    try:
        if hasattr(os, "sysconf"):
            page_size = os.sysconf("SC_PAGE_SIZE")
            phys_pages = os.sysconf("SC_PHYS_PAGES")
            total_ram = int(page_size * phys_pages)
            ram_metrics = {"total_bytes": total_ram}
            ram_status = "ok" if total_ram >= 8 * 1024**3 else "warn"
            ram_details = f"Approx total RAM: {round(total_ram / 1024**3, 2)} GiB."
    except Exception:
        pass
    checks.append(
        DoctorCheck(
            name="ram",
            status=ram_status,
            details=ram_details,
            metrics=ram_metrics,
            recommendation=None
            if ram_status == "ok"
            else "Use Low Resource profile on smaller systems.",
        )
    )

    disk = shutil.disk_usage(DATA_DIR)
    free_gib = disk.free / 1024**3
    checks.append(
        DoctorCheck(
            name="disk",
            status="ok" if free_gib >= 2 else "warn",
            details=f"Free disk in data dir volume: {free_gib:.2f} GiB.",
            metrics={"free_bytes": disk.free, "total_bytes": disk.total},
            recommendation=None
            if free_gib >= 2
            else "Free up at least 2 GiB for model/cache stability.",
        )
    )

    has_default = bool(models.default_model_id)
    default_entry = next(
        (
            entry
            for entry in models.installed_models
            if entry.model_id == models.default_model_id
        ),
        None,
    )
    checks.append(
        DoctorCheck(
            name="model_installed",
            status="ok" if has_default and default_entry is not None else "warn",
            details=(
                f"Default model: {models.default_model_id}."
                if has_default and default_entry is not None
                else "No default model configured."
            ),
            recommendation=None
            if has_default
            else "Install/register a model and set it as default.",
        )
    )

    loadable = False
    if default_entry is not None and default_entry.local_path:
        loadable = Path(default_entry.local_path).exists()
    checks.append(
        DoctorCheck(
            name="model_loadable",
            status="ok" if loadable else "warn",
            details=(
                f"Default model file exists: {default_entry.local_path}."
                if loadable
                else "Default model is missing a local file path or file does not exist."
            ),
            recommendation=None
            if loadable
            else "Register a valid local model path or complete model download.",
        )
    )

    checks.append(
        DoctorCheck(
            name="backend_health",
            status="ok",
            details=f"Backend service is responding at {iso(now)}.",
        )
    )

    permissions_ok = len(config.allowed_folders) > 0
    checks.append(
        DoctorCheck(
            name="permissions_config",
            status="ok" if permissions_ok else "warn",
            details=(
                f"Allowed folders configured: {len(config.allowed_folders)}."
                if permissions_ok
                else "No allowed folders configured."
            ),
            recommendation=None
            if permissions_ok
            else "Add at least one allowed folder in Settings -> Permissions.",
        )
    )

    statuses = [item.status for item in checks]
    overall: Literal["ok", "warn", "fail"]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"
    summary = (
        f"Doctor report: {overall.upper()} with "
        f"{statuses.count('ok')} ok, {statuses.count('warn')} warn, {statuses.count('fail')} fail checks."
    )
    return DoctorReport(
        report_id=uuid4(),
        generated_at=iso(now),
        overall_status=overall,
        checks=checks,
        summary=summary,
    )


def redact_line(line: str, redact_paths: bool) -> str:
    if not redact_paths:
        return line
    rewritten = line
    rewritten = rewritten.replace(str(DATA_DIR.resolve()), "{{DATA_DIR}}")
    for idx, folder in enumerate(get_config_snapshot().allowed_folders, start=1):
        marker = f"{{{{ALLOWED_FOLDER_{idx}}}}}"
        try:
            rewritten = rewritten.replace(str(Path(folder).resolve()), marker)
        except Exception:
            continue
    return rewritten


def task_trace_to_markdown(trace: TaskTrace) -> str:
    lines = [
        f"# Task {trace.task_id}",
        f"- Status: {trace.status}",
        f"- Plan: {trace.plan_id}",
        f"- Started: {trace.started_at}",
        f"- Ended: {trace.ended_at or 'n/a'}",
        f"- Agent: {trace.agent or 'n/a'}",
        "",
        "## Events",
    ]
    for event in trace.events:
        step = f" ({event.step_id})" if event.step_id else ""
        lines.append(
            f"- [{event.timestamp}] [{event.level.upper()}]{step} {event.message}"
        )
    return "\n".join(lines)


def doctor_report_to_markdown(report: DoctorReport) -> str:
    lines = [
        "# Doctor Report",
        f"- Generated: {report.generated_at}",
        f"- Overall Status: {report.overall_status}",
        "",
        "## Checks",
    ]
    for check in report.checks:
        recommendation = (
            f" Recommendation: {check.recommendation}" if check.recommendation else ""
        )
        lines.append(
            f"- **{check.name}** [{check.status}] {check.details}{recommendation}"
        )
    if report.summary:
        lines.extend(["", f"Summary: {report.summary}"])
    return "\n".join(lines)


def detect_search_query(prompt: str) -> str:
    quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", prompt)
    for pair in quoted:
        value = pair[0] or pair[1]
        if value.strip():
            return value.strip()
    if "todo" in prompt.lower():
        return "TODO"
    return "TODO"


def detect_file_search_confidence(prompt: str) -> tuple[float, bool]:
    lowered = prompt.lower()
    has_search_verb = any(word in lowered for word in ("search", "find", "look for"))
    has_file_scope = any(
        word in lowered for word in ("file", "folder", "project", "directory")
    )
    has_quoted_target = bool(re.findall(r"'([^']+)'|\"([^\"]+)\"", prompt))

    if has_search_verb and has_file_scope and has_quoted_target:
        return 0.95, True
    if has_search_verb and has_file_scope:
        return 0.82, True
    if "file" in lowered and any(
        word in lowered for word in ("help", "maybe", "around")
    ):
        return 0.45, False
    return 0.55, False


def detect_shell_exec_confidence(prompt: str) -> tuple[float, bool]:
    lowered = prompt.lower().strip()
    indicators = ("run command", "execute command", "shell", "terminal")
    has_indicator = any(token in lowered for token in indicators)
    has_code_block = "`" in prompt
    if has_indicator and has_code_block:
        return 0.93, True
    if has_indicator:
        return 0.84, True
    return 0.40, False


def extract_shell_command(prompt: str) -> str:
    inline = re.findall(r"`([^`]+)`", prompt)
    for item in inline:
        if item.strip():
            return item.strip()
    marker = "run command"
    lowered = prompt.lower()
    if marker in lowered:
        idx = lowered.index(marker) + len(marker)
        tail = prompt[idx:].strip(": ").strip()
        if tail:
            return tail
    return "pwd"


def build_plan(request: RouterPlanRequest) -> Plan:
    prompt = request.prompt.strip()
    lowered = prompt.lower()
    plan_id = uuid4()
    created_at = iso(now_utc())
    base_folder = (
        request.allowed_folders[0] if request.allowed_folders else str(Path.cwd())
    )

    router_confidence, should_route_file_search = detect_file_search_confidence(prompt)
    shell_confidence, should_route_shell_exec = detect_shell_exec_confidence(prompt)

    if router_confidence < ROUTER_CONFIDENCE_THRESHOLD:
        step = Step(
            step_id="step-1",
            agent="conversation",
            action="conversation.respond",
            inputs={"prompt": prompt},
            side_effects="none",
            preview="Router confidence is low. Respond conversationally with no system actions.",
        )
        return Plan(
            plan_id=plan_id,
            created_at=created_at,
            user_intent_summary="Respond safely due to ambiguous intent.",
            requires_approval=False,
            required_permissions=[],
            steps=[step],
            estimated_risk="low",
            dry_run=request.dry_run,
            router_confidence=router_confidence,
            router_fallback_used=True,
            explain="Router confidence is below threshold, so side effects are disabled.",
        )

    if should_route_file_search:
        query = detect_search_query(prompt)
        step = Step(
            step_id="step-1",
            agent="file",
            action="file.search",
            inputs={
                "root": base_folder,
                "query": query,
                "globs": ["**/*.txt", "**/*.md", "**/*.py"],
                "max_results": 10,
                "max_snippet_chars": 240,
            },
            side_effects="none",
            preview=f"Search for '{query}' under {base_folder} and return up to 10 matches.",
        )
        perms = [
            PermissionScope(
                type="file",
                mode="read",
                targets=[base_folder],
                reason="Need read access to search files in the selected folder.",
            )
        ]
        return Plan(
            plan_id=plan_id,
            created_at=created_at,
            user_intent_summary=f"Search files for '{query}'.",
            requires_approval=True,
            required_permissions=perms,
            steps=[step],
            estimated_risk="low",
            dry_run=request.dry_run,
            router_confidence=router_confidence,
            router_fallback_used=False,
            explain="This request requires reading files in the target folder.",
        )

    if should_route_shell_exec and shell_confidence >= SHELL_CONFIDENCE_THRESHOLD:
        command = extract_shell_command(prompt)
        step = Step(
            step_id="step-1",
            agent="shell",
            action="shell.exec",
            inputs={
                "command": command,
                "cwd": base_folder,
                "timeout_ms": DEFAULT_SHELL_TIMEOUT_MS,
                "max_output_chars": DEFAULT_SHELL_MAX_OUTPUT_CHARS,
            },
            side_effects="exec",
            preview=f"Execute shell command in {base_folder}: {command}",
        )
        perms = [
            PermissionScope(
                type="file",
                mode="read",
                targets=[base_folder],
                reason="Need folder scope to constrain shell working directory.",
            ),
            PermissionScope(
                type="shell",
                mode="exec",
                targets=[command],
                reason="Need explicit approval to execute shell commands.",
            ),
        ]
        return Plan(
            plan_id=plan_id,
            created_at=created_at,
            user_intent_summary="Execute a shell command with guardrails.",
            requires_approval=True,
            required_permissions=perms,
            steps=[step],
            estimated_risk="medium",
            dry_run=False,
            router_confidence=shell_confidence,
            router_fallback_used=False,
            explain="Shell command execution requires explicit approval and strict policy checks.",
        )

    step = Step(
        step_id="step-1",
        agent="conversation",
        action="conversation.respond",
        inputs={"prompt": prompt},
        side_effects="none",
        preview="Generate a direct response without system actions.",
    )
    return Plan(
        plan_id=plan_id,
        created_at=created_at,
        user_intent_summary="Answer the user prompt directly.",
        requires_approval=False,
        required_permissions=[],
        steps=[step],
        estimated_risk="low",
        dry_run=request.dry_run,
        router_confidence=0.90,
        router_fallback_used=False,
        explain="No file, shell, or network operations are required.",
    )


def action_card_from_plan(plan: Plan) -> ActionCard:
    what_will_happen = [step.preview for step in plan.steps]
    targets = ActionCardTargets()
    warnings = ["Review scope before approval."]

    for step in plan.steps:
        if step.action.startswith("file."):
            if "root" in step.inputs:
                targets.paths.append(str(step.inputs["root"]))
            if "folder" in step.inputs:
                targets.paths.append(str(step.inputs["folder"]))
            if "path" in step.inputs:
                targets.files.append(str(step.inputs["path"]))
        if step.action == "file.search" and "query" in step.inputs:
            warnings.append(f"Reads files to search for '{step.inputs['query']}'.")
        if step.action.startswith("shell.") and "command" in step.inputs:
            targets.commands.append(str(step.inputs["command"]))
        if step.action.startswith("browser.") and "url" in step.inputs:
            targets.urls.append(str(step.inputs["url"]))
        if step.side_effects in {"write", "exec", "network"}:
            warnings.append(
                f"Step {step.step_id} has side effects: {step.side_effects}."
            )

    return ActionCard(
        card_id=uuid4(),
        plan_id=plan.plan_id,
        title="Approval Required",
        what_will_happen=what_will_happen,
        exact_targets=targets,
        warnings=warnings,
        approve_token_request=ActionCardApproveTokenRequest(
            payload=ActionCardApproveTokenRequestPayload(plan_id=plan.plan_id)
        ),
    )


def plan_has_side_effects(plan: Plan) -> bool:
    return any(step.side_effects != "none" for step in plan.steps)


def consume_approval_token(
    plan: Plan, approval_token_id: UUID | None, required: bool
) -> ApprovalToken | None:
    if not required:
        return None
    if approval_token_id is None:
        raise HTTPException(status_code=403, detail="Approval token required")
    with approval_lock:
        token = approval_tokens.get(approval_token_id)
        if token is None:
            raise HTTPException(status_code=403, detail="Approval token not found")
        if token.plan_id != plan.plan_id:
            raise HTTPException(
                status_code=403, detail="Approval token does not match plan"
            )
        if token.consumed_at is not None:
            raise HTTPException(status_code=403, detail="Approval token already used")
        if now_utc() >= datetime.fromisoformat(token.expires_at.replace("Z", "+00:00")):
            raise HTTPException(status_code=403, detail="Approval token expired")
        token.consumed_at = iso(now_utc())
        approval_tokens[token.token_id] = token
        return token


@lru_cache(maxsize=1)
def get_blocked_paths() -> list[Path]:
    if os.name == "nt":
        blocked = [
            Path(os.environ.get("SystemRoot", r"C:\Windows")),
            Path(r"C:\Program Files"),
            Path(r"C:\Program Files (x86)"),
            Path(r"C:\ProgramData"),
        ]
    else:
        blocked = [
            Path("/bin"),
            Path("/boot"),
            Path("/dev"),
            Path("/etc"),
            Path("/lib"),
            Path("/lib64"),
            Path("/proc"),
            Path("/run"),
            Path("/sbin"),
            Path("/sys"),
            Path("/usr"),
            Path("/var"),
        ]
    return [path.resolve() for path in blocked]


def within_path(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_blocked_path(candidate: Path) -> bool:
    resolved = candidate.resolve()
    return any(within_path(resolved, blocked) for blocked in get_blocked_paths())


def get_allowed_read_roots(plan: Plan) -> list[Path]:
    roots: list[Path] = []
    for permission in plan.required_permissions:
        if permission.type == "file" and permission.mode == "read":
            roots.extend(Path(target).resolve() for target in permission.targets)
    return roots


def get_config_allowed_roots() -> list[Path]:
    config = get_config_snapshot()
    return [Path(folder).resolve() for folder in config.allowed_folders]


def ensure_file_read_scope(target_path: Path, allowed_roots: list[Path]) -> None:
    resolved = target_path.resolve()
    if is_blocked_path(resolved):
        raise HTTPException(status_code=403, detail=f"Blocked path: {resolved}")
    config_allowed_roots = get_config_allowed_roots()
    if not config_allowed_roots:
        raise HTTPException(
            status_code=403,
            detail="No folders are allowed yet. Add a folder to continue.",
        )
    if not any(within_path(resolved, root) for root in config_allowed_roots):
        raise HTTPException(
            status_code=403,
            detail=f"Path is outside configured allowed folders: {resolved}",
        )
    if not allowed_roots:
        raise HTTPException(
            status_code=403, detail="No allowed file read roots configured"
        )
    if not any(within_path(resolved, root) for root in allowed_roots):
        raise HTTPException(
            status_code=403, detail=f"Path is outside allowed read scope: {resolved}"
        )


def is_probably_binary(path: Path) -> bool:
    binary_exts = {
        ".exe",
        ".dll",
        ".bin",
        ".so",
        ".dylib",
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".zip",
        ".gz",
        ".7z",
        ".mp4",
        ".mp3",
    }
    if path.suffix.lower() in binary_exts:
        return True
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return True
    return b"\x00" in chunk


def make_snippet(text: str, query: str, max_snippet_chars: int) -> str:
    query_lower = query.lower()
    text_lower = text.lower()
    index = text_lower.find(query_lower)
    if index < 0:
        return ""
    start = max(0, index - (max_snippet_chars // 2))
    end = min(len(text), start + max_snippet_chars)
    snippet = text[start:end].replace("\n", " ").strip()
    return snippet[:max_snippet_chars]


def matches_glob(relative_path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch(relative_path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch(relative_path, pattern[3:]):
            return True
    return False


def file_search(
    *,
    root: str,
    query: str,
    globs: list[str],
    max_results: int,
    max_snippet_chars: int,
    allowed_roots: list[Path],
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    ensure_file_read_scope(root_path, allowed_roots)
    if not root_path.exists() or not root_path.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Root folder not found: {root_path}"
        )
    patterns = globs or ["**/*"]
    max_results = max(1, min(max_results, 100))
    max_snippet_chars = max(32, min(max_snippet_chars, 2000))
    start = time.perf_counter()
    scanned = 0
    skipped_binary = 0
    skipped_pattern = 0
    warnings: list[str] = []
    results: list[dict[str, Any]] = []

    for file_path in sorted(root_path.rglob("*"), key=lambda p: str(p).lower()):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(root_path).as_posix()
        if patterns and not matches_glob(relative, patterns):
            skipped_pattern += 1
            continue
        ensure_file_read_scope(file_path, allowed_roots)
        scanned += 1
        if is_probably_binary(file_path):
            skipped_binary += 1
            if len(warnings) < 5:
                warnings.append(f"skipped binary file: {file_path}")
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped_binary += 1
            if len(warnings) < 5:
                warnings.append(f"skipped non-text file: {file_path}")
            continue
        except OSError:
            if len(warnings) < 5:
                warnings.append(f"skipped unreadable file: {file_path}")
            continue
        if query.lower() in content.lower():
            results.append(
                {
                    "path": str(file_path),
                    "snippet": make_snippet(content, query, max_snippet_chars),
                    "match": query,
                }
            )
            if len(results) >= max_results:
                break

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "results": results,
        "scanned_files": scanned,
        "skipped_binary_files": skipped_binary,
        "skipped_pattern_files": skipped_pattern,
        "warnings": warnings,
        "elapsed_ms": elapsed_ms,
    }


def file_read_text(
    path: str, max_chars: int, allowed_roots: list[Path]
) -> dict[str, Any]:
    if not path:
        raise HTTPException(
            status_code=400, detail="file.read_text requires a path input"
        )
    file_path = Path(path).resolve()
    ensure_file_read_scope(file_path, allowed_roots)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {file_path}")
    max_chars = max(1, min(max_chars, 200_000))
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, detail=f"File is not valid UTF-8 text: {file_path}"
        )
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not read file {file_path}: {exc}"
        ) from exc
    truncated = len(content) > max_chars
    return {
        "path": str(file_path),
        "content": content[:max_chars],
        "truncated": truncated,
        "returned_chars": min(len(content), max_chars),
        "total_chars": len(content),
    }


def ensure_exec_scope(cwd: Path, plan: Plan) -> None:
    allowed_roots = get_allowed_read_roots(plan)
    ensure_file_read_scope(cwd, allowed_roots)


def normalize_shell_inputs(step: Step) -> tuple[list[str], Path, int, int]:
    raw_command = step.inputs.get("command")
    if isinstance(raw_command, list):
        argv = [str(item) for item in raw_command]
    elif isinstance(raw_command, str):
        try:
            argv = shlex.split(raw_command, posix=os.name != "nt")
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid shell command syntax: {exc}"
            ) from exc
    else:
        raise HTTPException(
            status_code=400, detail="shell.exec requires a command string or argv list"
        )
    if not argv:
        raise HTTPException(status_code=400, detail="shell.exec command is empty")

    raw_joined = " ".join(argv)
    forbidden_tokens = (";", "&&", "||", "|", ">", ">>", "<")
    if any(token in raw_joined for token in forbidden_tokens):
        raise HTTPException(
            status_code=403, detail="Command contains forbidden shell operators"
        )

    timeout_ms = int(step.inputs.get("timeout_ms", DEFAULT_SHELL_TIMEOUT_MS))
    max_output_chars = int(
        step.inputs.get("max_output_chars", DEFAULT_SHELL_MAX_OUTPUT_CHARS)
    )
    timeout_ms = max(100, min(timeout_ms, 120_000))
    max_output_chars = max(256, min(max_output_chars, 200_000))

    cwd_input = str(step.inputs.get("cwd", str(Path.cwd())))
    cwd = Path(cwd_input).resolve()
    return argv, cwd, timeout_ms, max_output_chars


def ensure_shell_enabled() -> None:
    if not get_config_snapshot().shell.enabled:
        raise HTTPException(status_code=403, detail="Shell is disabled in config")


def enforce_shell_deny_keywords(argv: list[str]) -> None:
    common = {"curl", "wget", "ssh"}
    windows_only = {
        "del",
        "erase",
        "rmdir",
        "rd",
        "format",
        "diskpart",
        "powershell",
        "cmd",
        "reg",
        "schtasks",
    }
    unix_only = {"rm", "sudo", "chmod", "chown", "dd", "mkfs", "mount"}
    deny = set(common)
    deny.update(windows_only if os.name == "nt" else unix_only)
    for token in argv:
        normalized = token.lower()
        if normalized in deny:
            raise HTTPException(
                status_code=403, detail=f"Command token denied by policy: {token}"
            )


def normalize_arg_path(arg: str, cwd: Path) -> Path:
    candidate = Path(arg)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def enforce_shell_allowlist(argv: list[str]) -> tuple[str, list[str]]:
    if argv[0] == "pwd" and len(argv) == 1:
        return "internal", argv
    if argv[0] == "ls" and len(argv) in (1, 2):
        return "internal", argv
    if argv[0] == "cat" and len(argv) == 2:
        return "internal", argv
    if argv[0] == "grep" and len(argv) in (3, 4):
        if len(argv) == 4 and argv[3] != "--recursive":
            raise HTTPException(
                status_code=403,
                detail="Only --recursive is allowed as fourth grep argument",
            )
        return "internal", argv
    if argv[0] == "find" and len(argv) in (2, 3):
        return "internal", argv

    allowed_external = {
        ("git", "status"),
        ("git", "diff"),
        ("git", "log"),
        ("python", "--version"),
        ("python", "-m", "pip", "--version"),
        ("node", "--version"),
        ("npm", "--version"),
    }
    if tuple(argv) in allowed_external:
        return "external", argv
    raise HTTPException(
        status_code=403, detail=f"Command not allowlisted: {' '.join(argv)}"
    )


def truncate_output(text: str, max_output_chars: int) -> tuple[str, bool]:
    if len(text) <= max_output_chars:
        return text, False
    return text[:max_output_chars], True


def execute_internal_shell(
    argv: list[str], cwd: Path, plan: Plan, timeout_ms: int
) -> tuple[str, str, int, bool]:
    start = time.perf_counter()

    def ensure_not_timed_out() -> None:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > timeout_ms:
            raise TimeoutError("Shell command timed out")

    if argv[0] == "pwd":
        return str(cwd) + "\n", "", 0, False

    if argv[0] == "ls":
        target = cwd if len(argv) == 1 else normalize_arg_path(argv[1], cwd)
        ensure_exec_scope(target, plan)
        if not target.exists() or not target.is_dir():
            return "", f"ls target not found: {target}\n", 1, False
        entries = sorted(item.name for item in target.iterdir())
        ensure_not_timed_out()
        return "\n".join(entries) + ("\n" if entries else ""), "", 0, False

    if argv[0] == "cat":
        target = normalize_arg_path(argv[1], cwd)
        ensure_exec_scope(target, plan)
        if not target.exists() or not target.is_file():
            return "", f"cat target not found: {target}\n", 1, False
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return "", f"cat only supports UTF-8 text files: {target}\n", 1, False
        ensure_not_timed_out()
        return content, "", 0, False

    if argv[0] == "grep":
        pattern = argv[1]
        target = normalize_arg_path(argv[2], cwd)
        recursive = len(argv) == 4 and argv[3] == "--recursive"
        ensure_exec_scope(target, plan)
        matches: list[str] = []
        files: list[Path]
        if target.is_file():
            files = [target]
        elif target.is_dir():
            files = sorted(target.rglob("*")) if recursive else sorted(target.glob("*"))
            files = [item for item in files if item.is_file()]
        else:
            return "", f"grep target not found: {target}\n", 1, False
        for file_path in files:
            ensure_exec_scope(file_path, plan)
            ensure_not_timed_out()
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for idx, line in enumerate(lines, start=1):
                if pattern in line:
                    matches.append(f"{file_path}:{idx}:{line}")
        return ("\n".join(matches) + ("\n" if matches else "")), "", 0, False

    if argv[0] == "find":
        root = normalize_arg_path(argv[1], cwd)
        pattern = argv[2] if len(argv) == 3 else "*"
        ensure_exec_scope(root, plan)
        if not root.exists() or not root.is_dir():
            return "", f"find root not found: {root}\n", 1, False
        matches: list[str] = []
        for item in sorted(root.rglob("*")):
            ensure_not_timed_out()
            if fnmatch(item.name, pattern):
                ensure_exec_scope(item, plan)
                matches.append(str(item))
        return ("\n".join(matches) + ("\n" if matches else "")), "", 0, False

    return "", f"Unsupported internal command: {argv[0]}\n", 1, False


def execute_external_shell(
    argv: list[str], cwd: Path, timeout_ms: int
) -> tuple[str, str, int, bool]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000.0,
            check=False,
        )
        return (
            completed.stdout or "",
            completed.stderr or "",
            int(completed.returncode),
            False,
        )
    except subprocess.TimeoutExpired:
        return "", "command timed out\n", 124, True
    except FileNotFoundError:
        return "", f"command not found: {argv[0]}\n", 127, False
    except Exception as exc:
        return "", f"command execution failed: {exc}\n", 1, False


def execute_shell_step(step: Step, plan: Plan) -> dict[str, Any]:
    if step.side_effects != "exec":
        raise HTTPException(
            status_code=403, detail="shell.exec step must declare side_effects=exec"
        )
    ensure_shell_enabled()
    argv, cwd, timeout_ms, max_output_chars = normalize_shell_inputs(step)
    append_backend_log("info", f"shell.exec requested argv={argv} cwd={cwd}")
    try:
        ensure_exec_scope(cwd, plan)
        enforce_shell_deny_keywords(argv)
        mode, argv = enforce_shell_allowlist(argv)
    except HTTPException as exc:
        append_backend_log("warn", f"shell.exec denied reason={exc.detail}")
        raise
    try:
        if mode == "internal":
            stdout, stderr, exit_code, timed_out = execute_internal_shell(
                argv, cwd, plan, timeout_ms
            )
        else:
            stdout, stderr, exit_code, timed_out = execute_external_shell(
                argv, cwd, timeout_ms
            )
    except TimeoutError:
        stdout, stderr, exit_code, timed_out = "", "command timed out\n", 124, True
    combined = (stdout or "") + (stderr or "")
    truncated_output, truncated = truncate_output(combined, max_output_chars)
    append_backend_log(
        "info",
        f"shell.exec {'allowed' if exit_code == 0 else 'completed'} exit_code={exit_code} truncated={truncated} timeout={timed_out}",
    )
    return {
        "argv": argv,
        "cwd": str(cwd),
        "stdout": stdout,
        "stderr": stderr,
        "output": truncated_output,
        "truncated": truncated,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "timeout_ms": timeout_ms,
        "max_output_chars": max_output_chars,
    }


@app.get("/v1/health", dependencies=[Depends(require_bearer)])
def get_health() -> dict[str, Any]:
    return {"status": "ok", "time": iso(now_utc())}


@app.get("/v1/version", dependencies=[Depends(require_bearer)])
def get_version() -> dict[str, str]:
    return {"version": APP_VERSION}


@app.get(
    "/v1/models", dependencies=[Depends(require_bearer)], response_model=ModelsState
)
def get_models() -> ModelsState:
    return get_models_snapshot()


@app.post(
    "/v1/models/download",
    dependencies=[Depends(require_bearer)],
    response_model=ModelsState,
)
def post_models_download(request: ModelDownloadRequest) -> ModelsState:
    state = get_models_snapshot()
    display_name = request.display_name or request.model_id
    local_path: str | None = None
    status: Literal["registered", "download_stubbed"] = "download_stubbed"
    if request.local_path:
        candidate = Path(request.local_path).resolve()
        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(
                status_code=400, detail=f"Model file not found: {candidate}"
            )
        local_path = str(candidate)
        status = "registered"
    entry = ModelEntry(
        model_id=request.model_id,
        display_name=display_name,
        local_path=local_path,
        status=status,
    )
    state.installed_models = [
        item for item in state.installed_models if item.model_id != request.model_id
    ]
    state.installed_models.append(entry)
    if state.default_model_id is None:
        state.default_model_id = request.model_id
    with models_lock:
        global current_models
        current_models = state
        write_models_state(current_models)
    return get_models_snapshot()


@app.post(
    "/v1/models/set-default",
    dependencies=[Depends(require_bearer)],
    response_model=ModelsState,
)
def post_models_set_default(request: ModelSetDefaultRequest) -> ModelsState:
    state = get_models_snapshot()
    if not any(item.model_id == request.model_id for item in state.installed_models):
        raise HTTPException(
            status_code=404, detail=f"Model not installed: {request.model_id}"
        )
    state.default_model_id = request.model_id
    with models_lock:
        global current_models
        current_models = state
        write_models_state(current_models)
    return get_models_snapshot()


@app.get("/v1/config", dependencies=[Depends(require_bearer)], response_model=AppConfig)
def get_config() -> AppConfig:
    return get_config_snapshot()


@app.post(
    "/v1/config/reload",
    dependencies=[Depends(require_bearer)],
    response_model=AppConfig,
)
def post_config_reload() -> AppConfig:
    return reload_config()


@app.get(
    "/v1/doctor/report",
    dependencies=[Depends(require_bearer)],
    response_model=DoctorReport,
)
def get_doctor_report() -> DoctorReport:
    report = generate_doctor_report()
    append_backend_log("info", f"doctor report generated: {report.overall_status}")
    return report


@app.get("/v1/doctor/report/export", dependencies=[Depends(require_bearer)])
def get_doctor_report_export(format: Literal["md", "json"] = "json") -> dict[str, Any]:
    report = generate_doctor_report()
    if format == "md":
        return {
            "format": "md",
            "content": doctor_report_to_markdown(report),
            "file_name": f"doctor-{report.report_id}.md",
        }
    return {
        "format": "json",
        "content": report.model_dump(mode="json"),
        "file_name": f"doctor-{report.report_id}.json",
    }


@app.get(
    "/v1/tasks",
    dependencies=[Depends(require_bearer)],
    response_model=list[TaskSummary],
)
def get_tasks() -> list[TaskSummary]:
    return load_task_index()


@app.get(
    "/v1/tasks/{task_id}",
    dependencies=[Depends(require_bearer)],
    response_model=TaskTrace,
)
def get_task(task_id: UUID) -> TaskTrace:
    return load_task_trace(task_id)


@app.get("/v1/tasks/{task_id}/export", dependencies=[Depends(require_bearer)])
def get_task_export(
    task_id: UUID, format: Literal["md", "json"] = "json"
) -> dict[str, Any]:
    trace = load_task_trace(task_id)
    if format == "md":
        return {
            "format": "md",
            "content": task_trace_to_markdown(trace),
            "file_name": f"task-{task_id}.md",
        }
    return {
        "format": "json",
        "content": trace.model_dump(mode="json"),
        "file_name": f"task-{task_id}.json",
    }


@app.get(
    "/v1/logs/tail",
    dependencies=[Depends(require_bearer)],
    response_model=LogsTailResponse,
)
def get_logs_tail(lines: int = 200) -> LogsTailResponse:
    path = backend_log_path()
    if not path.exists():
        return LogsTailResponse(lines=[])
    content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    take = max(1, min(lines, 2000))
    return LogsTailResponse(lines=content[-take:])


@app.get(
    "/v1/logs/search",
    dependencies=[Depends(require_bearer)],
    response_model=LogsSearchResponse,
)
def get_logs_search(q: str, limit: int = 200) -> LogsSearchResponse:
    needle = q.lower().strip()
    if not needle:
        return LogsSearchResponse(matches=[])
    path = backend_log_path()
    if not path.exists():
        return LogsSearchResponse(matches=[])
    matches: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if needle in line.lower():
            matches.append(line)
            if len(matches) >= max(1, min(limit, 5000)):
                break
    return LogsSearchResponse(matches=matches)


@app.post(
    "/v1/logs/export",
    dependencies=[Depends(require_bearer)],
    response_model=LogsExportResponse,
)
def post_logs_export(request: LogsExportRequest) -> LogsExportResponse:
    path = backend_log_path()
    if not path.exists():
        return LogsExportResponse(format=request.format, content="")
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    redacted = [redact_line(line, request.redact_paths) for line in lines]
    if request.format == "jsonl":
        payload = "\n".join(json.dumps({"line": line}) for line in redacted)
    else:
        payload = "\n".join(redacted)
    return LogsExportResponse(format=request.format, content=payload)


@app.post(
    "/v1/router/plan", dependencies=[Depends(require_bearer)], response_model=Plan
)
def post_router_plan(request: RouterPlanRequest) -> Plan:
    plan = build_plan(request)
    stored_plans[plan.plan_id] = plan
    return plan


@app.post(
    "/v1/approvals/action-card",
    dependencies=[Depends(require_bearer)],
    response_model=ActionCard,
)
def post_action_card(request: ActionCardRequest) -> ActionCard:
    plan = stored_plans.get(request.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return action_card_from_plan(plan)


@app.post(
    "/v1/approvals/issue-token",
    dependencies=[Depends(require_bearer)],
    response_model=ApprovalToken,
)
def post_issue_token(request: IssueTokenRequest) -> ApprovalToken:
    if request.plan_id not in stored_plans:
        raise HTTPException(status_code=404, detail="Plan not found")
    issued_at = now_utc()
    token = ApprovalToken(
        token_id=uuid4(),
        plan_id=request.plan_id,
        issued_at=iso(issued_at),
        expires_at=iso(issued_at + timedelta(minutes=5)),
        ttl_seconds=300,
        one_time_use=True,
    )
    approval_tokens[token.token_id] = token
    return token


@app.post(
    "/v1/tasks/execute",
    dependencies=[Depends(require_bearer)],
    response_model=TaskTrace,
)
def post_tasks_execute(request: ExecuteTaskRequest) -> TaskTrace:
    stored_plan = stored_plans.get(request.plan.plan_id)
    plan = stored_plan if stored_plan is not None else request.plan
    trace = TaskTrace(
        task_id=uuid4(),
        plan_id=plan.plan_id,
        status="running",
        started_at=iso(now_utc()),
        agent=plan.steps[0].agent if plan.steps else None,
        events=[],
    )
    if plan.dry_run and plan_has_side_effects(plan):
        raise HTTPException(
            status_code=403, detail="Dry-run plans cannot execute side-effect steps"
        )

    token_required = plan.requires_approval or plan_has_side_effects(plan)
    token = consume_approval_token(plan, request.approval_token_id, token_required)
    if token is not None:
        trace.events.append(
            TaskEvent(
                timestamp=iso(now_utc()),
                level="info",
                message="Approval token validated",
                details={"token_id": str(token.token_id)},
            )
        )
        append_backend_log("info", f"approval token validated for task {trace.task_id}")

    try:
        for step in plan.steps:
            trace.events.append(
                TaskEvent(
                    timestamp=iso(now_utc()),
                    level="info",
                    step_id=step.step_id,
                    message=f"Executing {step.action}",
                    details={"preview": step.preview},
                )
            )
            if step.action == "file.search":
                allowed_roots = get_allowed_read_roots(plan)
                root = str(
                    step.inputs.get("root", step.inputs.get("folder", Path.cwd()))
                )
                query = str(step.inputs.get("query", "TODO"))
                globs = list(step.inputs.get("globs", ["**/*"]))
                max_results = int(
                    step.inputs.get("max_results", step.inputs.get("limit", 10))
                )
                max_snippet_chars = int(step.inputs.get("max_snippet_chars", 240))
                trace.events.append(
                    TaskEvent(
                        timestamp=iso(now_utc()),
                        level="info",
                        step_id=step.step_id,
                        message="search started",
                        details={
                            "root": root,
                            "query": query,
                            "max_results": max_results,
                        },
                    )
                )
                search_result = file_search(
                    root=root,
                    query=query,
                    globs=globs,
                    max_results=max_results,
                    max_snippet_chars=max_snippet_chars,
                    allowed_roots=allowed_roots,
                )
                trace.events.append(
                    TaskEvent(
                        timestamp=iso(now_utc()),
                        level="info",
                        step_id=step.step_id,
                        message=f"scanned {search_result['scanned_files']} files",
                        details={
                            "scanned_files": search_result["scanned_files"],
                            "skipped_pattern_files": search_result[
                                "skipped_pattern_files"
                            ],
                            "skipped_binary_files": search_result[
                                "skipped_binary_files"
                            ],
                        },
                    )
                )
                for warning in search_result["warnings"]:
                    trace.events.append(
                        TaskEvent(
                            timestamp=iso(now_utc()),
                            level="warn",
                            step_id=step.step_id,
                            message=warning,
                        )
                    )
                trace.events.append(
                    TaskEvent(
                        timestamp=iso(now_utc()),
                        level="info",
                        step_id=step.step_id,
                        message=f"search completed in {search_result['elapsed_ms']} ms",
                        details={
                            "count": len(search_result["results"]),
                            "results": search_result["results"],
                            "elapsed_ms": search_result["elapsed_ms"],
                        },
                    )
                )
                append_backend_log(
                    "info",
                    f"task {trace.task_id} search completed count={len(search_result['results'])} elapsed_ms={search_result['elapsed_ms']}",
                )
            elif step.action == "file.read_text":
                allowed_roots = get_allowed_read_roots(plan)
                path = str(step.inputs.get("path"))
                max_chars = int(step.inputs.get("max_chars", 20_000))
                read_result = file_read_text(
                    path=path, max_chars=max_chars, allowed_roots=allowed_roots
                )
                trace.events.append(
                    TaskEvent(
                        timestamp=iso(now_utc()),
                        level="info",
                        step_id=step.step_id,
                        message="file read completed",
                        details=read_result,
                    )
                )
                append_backend_log("info", f"task {trace.task_id} file read completed")
            elif step.action == "conversation.respond":
                response_text = f"Echo: {step.inputs.get('prompt', '')}"
                trace.events.append(
                    TaskEvent(
                        timestamp=iso(now_utc()),
                        level="info",
                        step_id=step.step_id,
                        message="Conversation response generated",
                        details={"response": response_text},
                    )
                )
                append_backend_log(
                    "info", f"task {trace.task_id} conversation response generated"
                )
            elif step.action == "shell.exec":
                shell_result = execute_shell_step(step, plan)
                trace.events.append(
                    TaskEvent(
                        timestamp=iso(now_utc()),
                        level="info",
                        step_id=step.step_id,
                        message="shell command preview",
                        details={
                            "argv": shell_result["argv"],
                            "cwd": shell_result["cwd"],
                        },
                    )
                )
                trace.events.append(
                    TaskEvent(
                        timestamp=iso(now_utc()),
                        level="info",
                        step_id=step.step_id,
                        message="shell command completed",
                        details={
                            "exit_code": shell_result["exit_code"],
                            "timed_out": shell_result["timed_out"],
                            "truncated": shell_result["truncated"],
                            "output": shell_result["output"],
                        },
                    )
                )
                if shell_result["truncated"]:
                    trace.events.append(
                        TaskEvent(
                            timestamp=iso(now_utc()),
                            level="warn",
                            step_id=step.step_id,
                            message="shell output truncated",
                            details={
                                "max_output_chars": shell_result["max_output_chars"]
                            },
                        )
                    )
                if shell_result["timed_out"]:
                    trace.status = "timeout"
                    trace.ended_at = iso(now_utc())
                    persist_task_trace(trace)
                    append_backend_log("warn", f"task {trace.task_id} timed out")
                    return trace
            else:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported action: {step.action}"
                )
        trace.status = "completed"
        trace.ended_at = iso(now_utc())
        persist_task_trace(trace)
        append_backend_log("info", f"task {trace.task_id} completed")
        return trace
    except HTTPException:
        trace.status = "failed"
        trace.error = "HTTP exception during execution"
        trace.ended_at = iso(now_utc())
        persist_task_trace(trace)
        raise
    except Exception as exc:
        trace.status = "failed"
        trace.error = str(exc)
        trace.ended_at = iso(now_utc())
        trace.events.append(
            TaskEvent(
                timestamp=iso(now_utc()),
                level="error",
                message="Execution failed",
                details={"error": str(exc)},
            )
        )
        persist_task_trace(trace)
        append_backend_log("error", f"task {trace.task_id} failed: {exc}")
        return trace


if __name__ == "__main__":
    import uvicorn

    reload_config()
    reload_models()
    port = int(os.environ.get("LITECLAW_PORT", "8765"))
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=False)
