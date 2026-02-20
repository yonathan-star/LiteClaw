#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Manager, State};
use uuid::Uuid;

struct AppState {
    runtime: Mutex<BackendRuntime>,
}

struct BackendRuntime {
    token: String,
    base_url: String,
    log_path: String,
    backend_ready: bool,
    last_error: Option<String>,
    data_dir: PathBuf,
    backend_child: Option<Child>,
}

#[derive(Serialize)]
struct ApiConfig {
    base_url: String,
    token: String,
    backend_ready: bool,
    last_error: Option<String>,
    log_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct ShellConfig {
    enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
struct LocalConfig {
    allowed_folders: Vec<String>,
    shell: ShellConfig,
    history_enabled: bool,
}

impl Default for LocalConfig {
    fn default() -> Self {
        Self {
            allowed_folders: Vec::new(),
            shell: ShellConfig { enabled: false },
            history_enabled: true,
        }
    }
}

#[tauri::command]
fn get_api_config(state: State<'_, AppState>) -> ApiConfig {
    let runtime = state.runtime.lock().expect("runtime lock poisoned");
    ApiConfig {
        base_url: runtime.base_url.clone(),
        token: runtime.token.clone(),
        backend_ready: runtime.backend_ready,
        last_error: runtime.last_error.clone(),
        log_path: runtime.log_path.clone(),
    }
}

fn config_path(data_dir: &PathBuf) -> PathBuf {
    data_dir.join("config.json")
}

fn write_config_atomic(data_dir: &PathBuf, config: &LocalConfig) -> Result<(), String> {
    fs::create_dir_all(data_dir).map_err(|e| format!("failed creating data dir: {e}"))?;
    let path = config_path(data_dir);
    let temp = path.with_extension("tmp");
    let bytes =
        serde_json::to_vec_pretty(config).map_err(|e| format!("failed serializing config: {e}"))?;
    fs::write(&temp, bytes).map_err(|e| format!("failed writing temp config: {e}"))?;
    if path.exists() {
        fs::remove_file(&path).map_err(|e| format!("failed removing old config: {e}"))?;
    }
    fs::rename(&temp, &path).map_err(|e| format!("failed replacing config: {e}"))?;
    Ok(())
}

fn ensure_config_exists(data_dir: &PathBuf) -> Result<(), String> {
    let path = config_path(data_dir);
    if path.exists() {
        return Ok(());
    }
    write_config_atomic(data_dir, &LocalConfig::default())
}

fn read_local_config(data_dir: &PathBuf) -> Result<LocalConfig, String> {
    ensure_config_exists(data_dir)?;
    let path = config_path(data_dir);
    let content = fs::read_to_string(path).map_err(|e| format!("failed reading config: {e}"))?;
    serde_json::from_str::<LocalConfig>(&content).map_err(|e| format!("invalid config json: {e}"))
}

fn normalize_folder(path: &str) -> Result<String, String> {
    let raw = PathBuf::from(path);
    if !raw.exists() || !raw.is_dir() {
        return Err(format!("not a folder: {path}"));
    }
    let canonical = raw
        .canonicalize()
        .map_err(|e| format!("failed to canonicalize folder {path}: {e}"))?;
    Ok(canonical.to_string_lossy().to_string())
}

fn backend_reload_config(runtime: &BackendRuntime) -> Result<(), String> {
    if !runtime.backend_ready {
        return Err("backend is not ready".to_string());
    }
    let url = format!("{}/v1/config/reload", runtime.base_url);
    let response = ureq::post(&url)
        .set("Authorization", &format!("Bearer {}", runtime.token))
        .set("Content-Type", "application/json")
        .send_string("{}");
    match response {
        Ok(resp) if resp.status() == 200 => Ok(()),
        Ok(resp) => Err(format!("backend config reload failed: HTTP {}", resp.status())),
        Err(err) => Err(format!("backend config reload failed: {err}")),
    }
}

#[tauri::command]
fn get_local_config(state: State<'_, AppState>) -> Result<LocalConfig, String> {
    let runtime = state.runtime.lock().map_err(|_| "runtime lock poisoned".to_string())?;
    read_local_config(&runtime.data_dir)
}

#[tauri::command]
fn add_allowed_folder(state: State<'_, AppState>, path: String) -> Result<LocalConfig, String> {
    let mut runtime = state.runtime.lock().map_err(|_| "runtime lock poisoned".to_string())?;
    let normalized = normalize_folder(&path)?;
    let mut config = read_local_config(&runtime.data_dir)?;
    if !config.allowed_folders.iter().any(|entry| entry == &normalized) {
        config.allowed_folders.push(normalized);
        config.allowed_folders.sort();
        write_config_atomic(&runtime.data_dir, &config)?;
        backend_reload_config(&runtime)?;
    }
    Ok(config)
}

#[tauri::command]
fn remove_allowed_folder(
    state: State<'_, AppState>,
    path: String,
) -> Result<LocalConfig, String> {
    let runtime = state.runtime.lock().map_err(|_| "runtime lock poisoned".to_string())?;
    let normalized = normalize_folder(&path).unwrap_or(path);
    let mut config = read_local_config(&runtime.data_dir)?;
    config.allowed_folders.retain(|entry| entry != &normalized);
    write_config_atomic(&runtime.data_dir, &config)?;
    backend_reload_config(&runtime)?;
    Ok(config)
}

#[tauri::command]
fn set_shell_enabled(state: State<'_, AppState>, enabled: bool) -> Result<LocalConfig, String> {
    let runtime = state.runtime.lock().map_err(|_| "runtime lock poisoned".to_string())?;
    let mut config = read_local_config(&runtime.data_dir)?;
    config.shell.enabled = enabled;
    write_config_atomic(&runtime.data_dir, &config)?;
    backend_reload_config(&runtime)?;
    Ok(config)
}

#[tauri::command]
fn retry_backend(state: State<'_, AppState>) -> Result<ApiConfig, String> {
    let mut runtime = state.runtime.lock().map_err(|_| "runtime lock poisoned".to_string())?;
    spawn_backend(&mut runtime)?;
    Ok(ApiConfig {
        base_url: runtime.base_url.clone(),
        token: runtime.token.clone(),
        backend_ready: runtime.backend_ready,
        last_error: runtime.last_error.clone(),
        log_path: runtime.log_path.clone(),
    })
}

#[tauri::command]
fn read_backend_logs(state: State<'_, AppState>, lines: usize) -> Result<String, String> {
    let runtime = state.runtime.lock().map_err(|_| "runtime lock poisoned".to_string())?;
    let path = PathBuf::from(&runtime.log_path);
    let content = fs::read_to_string(path).map_err(|e| format!("failed reading logs: {e}"))?;
    let mut collected: Vec<&str> = content.lines().rev().take(lines.max(1)).collect();
    collected.reverse();
    Ok(collected.join("\n"))
}

fn backend_script_path() -> PathBuf {
    let here = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    here.join("..").join("..").join("backend").join("main.py")
}

fn find_open_port() -> Result<u16, String> {
    for port in 8765..8865 {
        if TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return Ok(port);
        }
    }
    Err("no open port found in 8765-8864".to_string())
}

fn backend_log_file(data_dir: &PathBuf) -> Result<File, String> {
    let logs_dir = data_dir.join("logs");
    fs::create_dir_all(&logs_dir).map_err(|e| format!("failed creating logs dir: {e}"))?;
    let path = logs_dir.join("backend.log");
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| format!("failed opening backend log file: {e}"))
}

fn poll_backend_health(base_url: &str, token: &str, timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    let health_url = format!("{base_url}/v1/health");
    while Instant::now() < deadline {
        let response = ureq::get(&health_url)
            .set("Authorization", &format!("Bearer {token}"))
            .call();
        if let Ok(resp) = response {
            if resp.status() == 200 {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err("backend health check timed out".to_string())
}

fn stop_backend(runtime: &mut BackendRuntime) {
    if let Some(child) = runtime.backend_child.as_mut() {
        let _ = child.kill();
        let _ = child.wait();
    }
    runtime.backend_child = None;
}

fn spawn_backend(runtime: &mut BackendRuntime) -> Result<(), String> {
    stop_backend(runtime);

    let port = find_open_port()?;
    let token = Uuid::new_v4().to_string();
    let base_url = format!("http://127.0.0.1:{port}");
    let script_path = backend_script_path();
    let log_file = backend_log_file(&runtime.data_dir)?;
    let stderr_file = log_file
        .try_clone()
        .map_err(|e| format!("failed cloning log file handle: {e}"))?;

    let child = Command::new("python")
        .arg(script_path.to_string_lossy().to_string())
        .env("LITECLAW_AUTH_TOKEN", token.clone())
        .env("LITECLAW_DATA_DIR", runtime.data_dir.to_string_lossy().to_string())
        .env("LITECLAW_PORT", port.to_string())
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(stderr_file))
        .spawn()
        .map_err(|e| format!("failed to spawn backend: {e}"))?;

    runtime.token = token;
    runtime.base_url = base_url;
    runtime.backend_child = Some(child);
    runtime.backend_ready = false;
    runtime.last_error = None;

    match poll_backend_health(&runtime.base_url, &runtime.token, Duration::from_secs(5)) {
        Ok(_) => {
            runtime.backend_ready = true;
            Ok(())
        }
        Err(err) => {
            runtime.backend_ready = false;
            runtime.last_error = Some(err.clone());
            stop_backend(runtime);
            Err(err)
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
            fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;
            let log_path = data_dir.join("logs").join("backend.log");

            let mut runtime = BackendRuntime {
                token: String::new(),
                base_url: String::new(),
                log_path: log_path.to_string_lossy().to_string(),
                backend_ready: false,
                last_error: None,
                data_dir,
                backend_child: None,
            };
            ensure_config_exists(&runtime.data_dir)?;
            if let Err(err) = spawn_backend(&mut runtime) {
                runtime.last_error = Some(err);
            }
            app.manage(AppState {
                runtime: Mutex::new(runtime),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_api_config,
            get_local_config,
            add_allowed_folder,
            remove_allowed_folder,
            set_shell_enabled,
            retry_backend,
            read_backend_logs
        ])
        .build(tauri::generate_context!())
        .expect("failed to build LiteClaw desktop app")
        .run(|app, event| match event {
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                let state = app.state::<AppState>();
                if let Ok(mut runtime) = state.runtime.lock() {
                    stop_backend(&mut runtime);
                }
            }
            _ => {}
        });
}
