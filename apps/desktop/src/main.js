import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

const statusBadge = document.getElementById("status-badge");
const modeToggleButton = document.getElementById("mode-toggle-btn");
const advancedPanel = document.getElementById("advanced-panel");
const advancedTabs = document.querySelectorAll(".advanced-tab-btn");
const advancedTabViews = document.querySelectorAll(".advanced-tab");

const promptInput = document.getElementById("prompt");
const runButton = document.getElementById("run-btn");
const planOutput = document.getElementById("plan-output");
const actionCardOutput = document.getElementById("action-card-output");
const backendLogsOutput = document.getElementById("backend-logs-output");
const traceOutput = document.getElementById("trace-output");
const backendError = document.getElementById("backend-error");
const backendErrorText = document.getElementById("backend-error-text");
const retryButton = document.getElementById("retry-btn");
const showLogsButton = document.getElementById("show-logs-btn");
const addFolderButton = document.getElementById("add-folder-btn");
const shellEnabledCheckbox = document.getElementById("shell-enabled-checkbox");
const allowedFoldersList = document.getElementById("allowed-folders-list");
const noFoldersBanner = document.getElementById("no-folders-banner");
const bannerAddFolderButton = document.getElementById("banner-add-folder-btn");
const modelsList = document.getElementById("models-list");
const modelsEmpty = document.getElementById("models-empty");
const downloadModelButton = document.getElementById("download-model-btn");
const registerModelButton = document.getElementById("register-model-btn");

const tasksList = document.getElementById("tasks-list");
const selectedTraceOutput = document.getElementById("selected-trace-output");
const traceLevelFilter = document.getElementById("trace-level-filter");
const copyTraceButton = document.getElementById("copy-trace-btn");
const exportTraceMdButton = document.getElementById("export-trace-md-btn");
const exportTraceJsonButton = document.getElementById("export-trace-json-btn");

const logsRefreshButton = document.getElementById("logs-refresh-btn");
const logsAutoRefreshCheckbox = document.getElementById("logs-auto-refresh");
const logsSearchInput = document.getElementById("logs-search-input");
const logsSearchButton = document.getElementById("logs-search-btn");
const logsRedactCheckbox = document.getElementById("logs-redact-checkbox");
const logsExportButton = document.getElementById("logs-export-btn");
const logsOutput = document.getElementById("logs-output");

const doctorRunButton = document.getElementById("doctor-run-btn");
const doctorExportJsonButton = document.getElementById(
  "doctor-export-json-btn",
);
const doctorExportMdButton = document.getElementById("doctor-export-md-btn");
const doctorOutput = document.getElementById("doctor-output");

let apiConfig = null;
let localConfig = { allowed_folders: [], shell: { enabled: false } };
let modelsState = { installed_models: [], default_model_id: null };
let advancedMode = false;
let selectedTask = null;
let selectedTaskTrace = null;
let logsIntervalId = null;
let latestDoctor = null;

function renderJson(el, data) {
  el.textContent = JSON.stringify(data, null, 2);
}

function downloadTextFile(fileName, content, mimeType = "text/plain") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function setActiveAdvancedTab(name) {
  advancedTabs.forEach((button) => {
    button.disabled = button.dataset.tab === name;
  });
  advancedTabViews.forEach((view) => {
    view.classList.toggle("hidden", view.id !== `advanced-${name}`);
  });
}

function setMode(isAdvanced) {
  advancedMode = isAdvanced;
  advancedPanel.classList.toggle("hidden", !advancedMode);
  modeToggleButton.textContent = advancedMode
    ? "Switch to Simple"
    : "Switch to Advanced";
}

async function api(path, method = "GET", body = null) {
  const options = {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiConfig.token}`,
    },
  };
  if (body) options.body = JSON.stringify(body);
  const response = await fetch(`${apiConfig.base_url}${path}`, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return response.json();
}

function setBackendReadyUI(ready, message = "") {
  runButton.disabled = !ready;
  if (ready) {
    statusBadge.textContent = "Backend Online";
    statusBadge.style.background = "#bbf7d0";
    backendError.classList.add("hidden");
    backendErrorText.textContent = "";
  } else {
    statusBadge.textContent = "Backend Offline";
    statusBadge.style.background = "#fecaca";
    backendError.classList.remove("hidden");
    backendErrorText.textContent = message || "Backend failed to start.";
  }
}

async function fetchBackendLogs() {
  try {
    const logs = await invoke("read_backend_logs", { lines: 200 });
    backendLogsOutput.textContent = logs || "(no logs)";
  } catch (err) {
    backendLogsOutput.textContent = String(err);
  }
}

function renderAllowedFolders() {
  allowedFoldersList.innerHTML = "";
  const folders = localConfig.allowed_folders || [];
  if (folders.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No folders added yet.";
    allowedFoldersList.appendChild(li);
    return;
  }
  for (const folder of folders) {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.className = "folder-path";
    span.textContent = folder;
    const removeButton = document.createElement("button");
    removeButton.textContent = "Remove";
    removeButton.addEventListener("click", async () => {
      try {
        localConfig = await invoke("remove_allowed_folder", { path: folder });
        renderAllowedFolders();
      } catch (err) {
        traceOutput.textContent = String(err);
      }
    });
    li.appendChild(span);
    li.appendChild(removeButton);
    allowedFoldersList.appendChild(li);
  }
}

async function refreshLocalConfig() {
  localConfig = await invoke("get_local_config");
  shellEnabledCheckbox.checked = !!localConfig.shell?.enabled;
  renderAllowedFolders();
}

function renderModels() {
  modelsList.innerHTML = "";
  const installed = modelsState.installed_models || [];
  modelsEmpty.classList.toggle("hidden", installed.length > 0);
  for (const model of installed) {
    const li = document.createElement("li");
    const span = document.createElement("span");
    const isDefault = modelsState.default_model_id === model.model_id;
    span.className = "folder-path";
    span.textContent = `${model.display_name} (${model.model_id})${isDefault ? " [default]" : ""}`;
    li.appendChild(span);
    if (!isDefault) {
      const button = document.createElement("button");
      button.textContent = "Set Default";
      button.addEventListener("click", async () => {
        try {
          modelsState = await api("/v1/models/set-default", "POST", {
            model_id: model.model_id,
          });
          renderModels();
        } catch (err) {
          traceOutput.textContent = String(err);
        }
      });
      li.appendChild(button);
    }
    modelsList.appendChild(li);
  }
}

async function refreshModels() {
  modelsState = await api("/v1/models");
  renderModels();
}

async function addFolderFlow() {
  try {
    const selected = await open({ directory: true, multiple: false });
    if (!selected || typeof selected !== "string") return;
    localConfig = await invoke("add_allowed_folder", { path: selected });
    renderAllowedFolders();
    traceOutput.textContent = "Folder added.";
    noFoldersBanner.classList.add("hidden");
  } catch (err) {
    traceOutput.textContent = String(err);
  }
}

function renderSelectedTrace() {
  if (!selectedTaskTrace) {
    selectedTraceOutput.textContent = "(select a task)";
    return;
  }
  const filter = traceLevelFilter.value;
  const events = selectedTaskTrace.events.filter(
    (event) => filter === "all" || event.level === filter,
  );
  const lines = [
    `task_id: ${selectedTaskTrace.task_id}`,
    `status: ${selectedTaskTrace.status}`,
    "",
    ...events.map((event) => {
      const step = event.step_id ? ` (${event.step_id})` : "";
      return `[${event.timestamp}] [${event.level}]${step} ${event.message}`;
    }),
  ];
  selectedTraceOutput.textContent = lines.join("\n");
}

async function refreshTasks() {
  const tasks = await api("/v1/tasks");
  tasksList.innerHTML = "";
  if (!tasks.length) {
    const li = document.createElement("li");
    li.textContent = "No tasks yet.";
    tasksList.appendChild(li);
    selectedTask = null;
    selectedTaskTrace = null;
    renderSelectedTrace();
    return;
  }
  for (const task of tasks) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.className = "folder-path";
    label.textContent = `${task.started_at} | ${task.status} | ${task.agent || "n/a"}`;
    const openButton = document.createElement("button");
    openButton.textContent = "View";
    openButton.addEventListener("click", async () => {
      selectedTask = task;
      selectedTaskTrace = await api(`/v1/tasks/${task.task_id}`);
      renderSelectedTrace();
    });
    li.appendChild(label);
    li.appendChild(openButton);
    tasksList.appendChild(li);
  }
}

async function refreshLogsTail() {
  const data = await api("/v1/logs/tail?lines=200");
  logsOutput.textContent = (data.lines || []).join("\n");
}

async function runDoctor() {
  latestDoctor = await api("/v1/doctor/report");
  renderJson(doctorOutput, latestDoctor);
}

async function init() {
  try {
    apiConfig = await invoke("get_api_config");
    await refreshLocalConfig();
    if (!apiConfig.backend_ready) {
      setBackendReadyUI(
        false,
        apiConfig.last_error || "Backend failed to start.",
      );
      return;
    }
    await api("/v1/health");
    await refreshModels();
    await refreshTasks();
    await refreshLogsTail();
    await runDoctor();
    setBackendReadyUI(true);
  } catch (err) {
    setBackendReadyUI(false, String(err));
    traceOutput.textContent = String(err);
  }
}

modeToggleButton.addEventListener("click", async () => {
  setMode(!advancedMode);
  if (advancedMode) {
    await refreshTasks();
    await refreshLogsTail();
    await runDoctor();
  } else if (logsIntervalId) {
    clearInterval(logsIntervalId);
    logsIntervalId = null;
  }
});

advancedTabs.forEach((button) => {
  button.addEventListener("click", () => {
    setActiveAdvancedTab(button.dataset.tab);
  });
});

retryButton.addEventListener("click", async () => {
  traceOutput.textContent = "";
  try {
    apiConfig = await invoke("retry_backend");
    if (!apiConfig.backend_ready) {
      setBackendReadyUI(false, apiConfig.last_error || "Retry failed.");
      return;
    }
    await api("/v1/health");
    setBackendReadyUI(true);
  } catch (err) {
    setBackendReadyUI(false, String(err));
    traceOutput.textContent = String(err);
  }
});

showLogsButton.addEventListener("click", fetchBackendLogs);

runButton.addEventListener("click", async () => {
  traceOutput.textContent = "";
  backendLogsOutput.textContent = "";
  try {
    await refreshLocalConfig();
    const plan = await api("/v1/router/plan", "POST", {
      prompt: promptInput.value,
      allowed_folders: localConfig.allowed_folders || [],
      dry_run: true,
    });
    renderJson(planOutput, plan);

    const actionCard = await api("/v1/approvals/action-card", "POST", {
      plan_id: plan.plan_id,
    });
    renderJson(actionCardOutput, actionCard);

    const firstStep = plan.steps?.[0];
    if (
      firstStep &&
      firstStep.agent === "file" &&
      (!localConfig.allowed_folders || localConfig.allowed_folders.length === 0)
    ) {
      noFoldersBanner.classList.remove("hidden");
      traceOutput.textContent =
        "No folders are allowed yet. Add a folder to continue.";
      return;
    }
    noFoldersBanner.classList.add("hidden");

    const approval = await api("/v1/approvals/issue-token", "POST", {
      plan_id: plan.plan_id,
    });

    const trace = await api("/v1/tasks/execute", "POST", {
      plan,
      approval_token_id: approval.token_id,
    });
    renderJson(traceOutput, trace);
    await refreshTasks();
  } catch (err) {
    traceOutput.textContent = String(err);
  }
});

downloadModelButton.addEventListener("click", async () => {
  try {
    const id = window.prompt("Model ID", "tiny-q4");
    if (!id) return;
    modelsState = await api("/v1/models/download", "POST", {
      model_id: id,
      display_name: id,
    });
    renderModels();
  } catch (err) {
    traceOutput.textContent = String(err);
  }
});

registerModelButton.addEventListener("click", async () => {
  try {
    const selected = await open({ directory: false, multiple: false });
    if (!selected || typeof selected !== "string") return;
    const id = window.prompt("Model ID", "local-gguf");
    if (!id) return;
    modelsState = await api("/v1/models/download", "POST", {
      model_id: id,
      display_name: id,
      local_path: selected,
    });
    renderModels();
  } catch (err) {
    traceOutput.textContent = String(err);
  }
});

addFolderButton.addEventListener("click", addFolderFlow);
bannerAddFolderButton.addEventListener("click", addFolderFlow);
shellEnabledCheckbox.addEventListener("change", async () => {
  try {
    localConfig = await invoke("set_shell_enabled", {
      enabled: shellEnabledCheckbox.checked,
    });
    shellEnabledCheckbox.checked = !!localConfig.shell?.enabled;
  } catch (err) {
    traceOutput.textContent = String(err);
    shellEnabledCheckbox.checked = !!localConfig.shell?.enabled;
  }
});

traceLevelFilter.addEventListener("change", renderSelectedTrace);

copyTraceButton.addEventListener("click", async () => {
  if (!selectedTaskTrace) return;
  await navigator.clipboard.writeText(selectedTraceOutput.textContent || "");
});

exportTraceMdButton.addEventListener("click", async () => {
  if (!selectedTask) return;
  const payload = await api(
    `/v1/tasks/${selectedTask.task_id}/export?format=md`,
  );
  downloadTextFile(payload.file_name, payload.content, "text/markdown");
});

exportTraceJsonButton.addEventListener("click", async () => {
  if (!selectedTask) return;
  const payload = await api(
    `/v1/tasks/${selectedTask.task_id}/export?format=json`,
  );
  downloadTextFile(
    payload.file_name,
    JSON.stringify(payload.content, null, 2),
    "application/json",
  );
});

logsRefreshButton.addEventListener("click", refreshLogsTail);

logsAutoRefreshCheckbox.addEventListener("change", () => {
  if (logsAutoRefreshCheckbox.checked) {
    if (logsIntervalId) clearInterval(logsIntervalId);
    logsIntervalId = setInterval(() => {
      refreshLogsTail().catch((err) => {
        logsOutput.textContent = String(err);
      });
    }, 2000);
  } else if (logsIntervalId) {
    clearInterval(logsIntervalId);
    logsIntervalId = null;
  }
});

logsSearchButton.addEventListener("click", async () => {
  const q = logsSearchInput.value.trim();
  if (!q) return;
  const payload = await api(
    `/v1/logs/search?q=${encodeURIComponent(q)}&limit=200`,
  );
  logsOutput.textContent = (payload.matches || []).join("\n");
});

logsExportButton.addEventListener("click", async () => {
  const payload = await api("/v1/logs/export", "POST", {
    redact_paths: logsRedactCheckbox.checked,
    format: "txt",
  });
  downloadTextFile("liteclaw-logs.txt", payload.content, "text/plain");
});

doctorRunButton.addEventListener("click", runDoctor);

doctorExportJsonButton.addEventListener("click", async () => {
  const payload = await api("/v1/doctor/report/export?format=json");
  downloadTextFile(
    payload.file_name,
    JSON.stringify(payload.content, null, 2),
    "application/json",
  );
});

doctorExportMdButton.addEventListener("click", async () => {
  const payload = await api("/v1/doctor/report/export?format=md");
  downloadTextFile(payload.file_name, payload.content, "text/markdown");
});

setMode(false);
setActiveAdvancedTab("tasks");
init();
