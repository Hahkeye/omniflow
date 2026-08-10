#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Tauri shell talks to the long-lived Omniflow Python daemon over localhost TCP.
//! Models stay warm; progress streams as NDJSON; cancel is supported.

use serde::Serialize;
use serde_json::{json, Value};
use std::env;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::process::Command;
use tokio::sync::Mutex;
use tokio::time::sleep;

const DEFAULT_PORT: u16 = 17432;
const PROTOCOL_V: u64 = 1;

// ─── paths ───────────────────────────────────────────────────────────────────

fn home_dir() -> Option<PathBuf> {
    env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

fn looks_like_project_root(dir: &Path) -> bool {
    dir.join("diary_app").join("main.py").exists()
        || dir.join("diary_app").join("__main__.py").exists()
}

/// Walk parents looking for the Omniflow checkout (contains diary_app/).
fn find_project_root_from(start: &Path) -> Option<PathBuf> {
    let mut cur = Some(start.to_path_buf());
    for _ in 0..10 {
        if let Some(ref dir) = cur {
            if looks_like_project_root(dir) {
                return Some(dir.clone());
            }
            // also check parent of diary-frontend/src-tauri/target/...
            cur = dir.parent().map(|p| p.to_path_buf());
        } else {
            break;
        }
    }
    None
}

fn project_root() -> PathBuf {
    if let Ok(p) = env::var("DIARY_PROJECT_ROOT") {
        return PathBuf::from(p);
    }
    if let Ok(p) = env::var("OMNIFLOW_ROOT") {
        return PathBuf::from(p);
    }
    // Prefer cwd (dev: usually repo root or diary-frontend)
    if let Ok(cwd) = env::current_dir() {
        if let Some(root) = find_project_root_from(&cwd) {
            return root;
        }
        if let Some(root) = find_project_root_from(&cwd.join("..")) {
            return root.canonicalize().unwrap_or(root);
        }
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() {
            if let Some(root) = find_project_root_from(parent) {
                return root;
            }
        }
    }
    // Last resort: common local checkout layout (dev machines only)
    if let Some(home) = home_dir() {
        for candidate in [
            home.join("code").join("omniflow"),
            home.join("omniflow"),
            home.join("src").join("omniflow"),
        ] {
            if looks_like_project_root(&candidate) {
                return candidate;
            }
        }
    }
    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

/// Prefer explicit env, then project `.venv`, then system python.
fn python_bin() -> String {
    if let Ok(p) = env::var("DIARY_PYTHON") {
        return p;
    }
    let root = project_root();
    let venv_candidates = if cfg!(windows) {
        vec![
            root.join(".venv").join("Scripts").join("python.exe"),
            root.join("venv").join("Scripts").join("python.exe"),
        ]
    } else {
        vec![
            root.join(".venv").join("bin").join("python"),
            root.join(".venv").join("bin").join("python3"),
            root.join("venv").join("bin").join("python"),
            root.join("venv").join("bin").join("python3"),
        ]
    };
    for c in venv_candidates {
        if c.is_file() {
            return c.to_string_lossy().into_owned();
        }
    }
    if let Ok(p) = env::var("PYTHON") {
        return p;
    }
    if cfg!(windows) {
        "python".to_string()
    } else {
        "python3".to_string()
    }
}

fn diary_dir() -> PathBuf {
    home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("diary")
}

fn daemon_state_path() -> PathBuf {
    diary_dir().join("daemon.json")
}

// ─── daemon state ────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
struct DaemonEndpoint {
    host: String,
    port: u16,
    token: String,
}

struct AppState {
    /// Last known endpoint (refreshed from disk on ensure)
    endpoint: Mutex<Option<DaemonEndpoint>>,
    /// Active request id for cancel
    active_request: Mutex<Option<String>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            endpoint: Mutex::new(None),
            active_request: Mutex::new(None),
        }
    }
}

fn read_daemon_state_file() -> Option<DaemonEndpoint> {
    let path = daemon_state_path();
    let text = std::fs::read_to_string(path).ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    Some(DaemonEndpoint {
        host: v
            .get("host")
            .and_then(|x| x.as_str())
            .unwrap_or("127.0.0.1")
            .to_string(),
        port: v.get("port").and_then(|x| x.as_u64()).unwrap_or(DEFAULT_PORT as u64) as u16,
        token: v
            .get("token")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string(),
    })
}

async fn tcp_request(
    ep: &DaemonEndpoint,
    cmd: &str,
    params: Value,
    request_id: &str,
    progress_tx: Option<tokio::sync::mpsc::UnboundedSender<Value>>,
    timeout: Duration,
) -> Result<Value, String> {
    let addr = format!("{}:{}", ep.host, ep.port);
    let stream = tokio::time::timeout(Duration::from_secs(10), TcpStream::connect(&addr))
        .await
        .map_err(|_| format!("connect timeout to daemon at {}", addr))?
        .map_err(|e| format!("connect to daemon at {}: {}", addr, e))?;

    stream
        .set_nodelay(true)
        .map_err(|e| format!("nodelay: {}", e))?;

    let (reader, mut writer) = stream.into_split();
    let req = json!({
        "v": PROTOCOL_V,
        "id": request_id,
        "token": ep.token,
        "cmd": cmd,
        "params": params,
    });
    let line = format!("{}\n", req);
    writer
        .write_all(line.as_bytes())
        .await
        .map_err(|e| format!("write: {}", e))?;

    let mut lines = BufReader::new(reader).lines();
    let deadline = tokio::time::Instant::now() + timeout;

    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() {
            return Err("daemon request timed out".into());
        }
        let line = tokio::time::timeout(remaining, lines.next_line())
            .await
            .map_err(|_| "daemon request timed out".to_string())?
            .map_err(|e| format!("read: {}", e))?;
        let Some(line) = line else {
            return Err("daemon closed connection".into());
        };
        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }
        let msg: Value = serde_json::from_str(&line)
            .map_err(|e| format!("invalid daemon JSON: {} — {}", e, line))?;
        let mtype = msg.get("type").and_then(|x| x.as_str()).unwrap_or("");
        if mtype == "progress" {
            if let Some(ref tx) = progress_tx {
                let _ = tx.send(msg);
            }
            continue;
        }
        // result (or any message with ok)
        if mtype == "result" || msg.get("ok").is_some() {
            return Ok(msg);
        }
    }
}

async fn spawn_daemon_process() -> Result<(), String> {
    let root = project_root();
    let mut child = Command::new(python_bin())
        .arg("-m")
        .arg("diary_app")
        .arg("serve")
        .arg("--detach")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(format!("{}", DEFAULT_PORT))
        .current_dir(&root)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| {
            format!(
                "Failed to spawn daemon (root={:?}, python={}): {}",
                root,
                python_bin(),
                e
            )
        })?;
    // Detached parent exits quickly
    let _ = child.wait().await;
    Ok(())
}

async fn ping_ep(ep: &DaemonEndpoint) -> bool {
    let rid = format!("ping-{}", uuid_like());
    tcp_request(
        ep,
        "ping",
        json!({}),
        &rid,
        None,
        Duration::from_secs(2),
    )
    .await
    .map(|v| v.get("ok").and_then(|x| x.as_bool()).unwrap_or(false))
    .unwrap_or(false)
}

async fn ensure_daemon(state: &AppState) -> Result<DaemonEndpoint, String> {
    // Fast path: cached + ping
    {
        let guard = state.endpoint.lock().await;
        if let Some(ep) = guard.clone() {
            drop(guard);
            if ping_ep(&ep).await {
                return Ok(ep);
            }
        }
    }

    // Disk state
    if let Some(ep) = read_daemon_state_file() {
        if ping_ep(&ep).await {
            *state.endpoint.lock().await = Some(ep.clone());
            return Ok(ep);
        }
    }

    // Start
    spawn_daemon_process().await?;

    for _ in 0..60 {
        sleep(Duration::from_millis(250)).await;
        if let Some(ep) = read_daemon_state_file() {
            if ping_ep(&ep).await {
                *state.endpoint.lock().await = Some(ep.clone());
                return Ok(ep);
            }
        }
    }
    Err(format!(
        "Daemon did not become ready. Check {} and run: python -m diary_app serve --detach",
        daemon_state_path().display()
    ))
}

fn uuid_like() -> String {
    format!(
        "{:x}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    )
}

fn ok_flag(v: &Value) -> bool {
    v.get("ok").and_then(|x| x.as_bool()).unwrap_or(false)
}

fn err_msg(v: &Value) -> Option<String> {
    v.get("error")
        .and_then(|x| x.as_str())
        .map(|s| s.to_string())
}

/// Call daemon command; optional progress → frontend event `diary-progress`.
async fn daemon_call(
    app: &AppHandle,
    state: &AppState,
    cmd: &str,
    params: Value,
    with_progress: bool,
    timeout_secs: u64,
) -> Result<Value, String> {
    let ep = ensure_daemon(state).await?;
    let rid = uuid_like();
    *state.active_request.lock().await = Some(rid.clone());

    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<Value>();
    let progress_tx = if with_progress { Some(tx) } else { None };

    let app2 = app.clone();
    let progress_task = if with_progress {
        Some(tokio::spawn(async move {
            while let Some(msg) = rx.recv().await {
                let _ = app2.emit("diary-progress", msg);
            }
        }))
    } else {
        None
    };

    let result = tcp_request(
        &ep,
        cmd,
        params,
        &rid,
        progress_tx,
        Duration::from_secs(timeout_secs),
    )
    .await;

    // Drop sender side by ending tcp_request; finish progress task
    if let Some(task) = progress_task {
        // channel closes when progress_tx dropped inside tcp_request return
        let _ = task.await;
    }

    let mut active = state.active_request.lock().await;
    if active.as_deref() == Some(rid.as_str()) {
        *active = None;
    }
    result
}

// ─── result types (stable for frontend) ──────────────────────────────────────

#[derive(Serialize)]
struct TranscribeResult {
    success: bool,
    output: String,
    entry_id: Option<String>,
    error: Option<String>,
}

#[derive(Serialize)]
struct RecordResult {
    success: bool,
    wav_path: Option<String>,
    error: Option<String>,
}

#[derive(Serialize)]
struct HistoryListResult {
    success: bool,
    entries_json: String,
    error: Option<String>,
}

#[derive(Serialize)]
struct HistoryEntryResult {
    success: bool,
    entry_json: String,
    transcript_text: String,
    analysis_text: String,
    audio_path: Option<String>,
    segments_json: String,
    error: Option<String>,
}

#[derive(Serialize)]
struct SearchResult {
    success: bool,
    hits_json: String,
    error: Option<String>,
}

#[derive(Serialize)]
struct RenameResult {
    success: bool,
    speaker_map_json: String,
    error: Option<String>,
}

#[derive(Serialize)]
struct RosterResult {
    success: bool,
    roster_json: String,
    error: Option<String>,
}

#[derive(Serialize)]
struct ExportCmdResult {
    success: bool,
    result_json: String,
    error: Option<String>,
}

#[derive(Serialize)]
struct DigestCmdResult {
    success: bool,
    markdown: String,
    path: Option<String>,
    error: Option<String>,
}

#[derive(Serialize)]
struct SimpleResult {
    success: bool,
    result_json: String,
    error: Option<String>,
}

// ─── commands ────────────────────────────────────────────────────────────────

#[tauri::command]
async fn daemon_status(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<SimpleResult, String> {
    match daemon_call(&app, &state, "status", json!({}), false, 5).await {
        Ok(v) => Ok(SimpleResult {
            success: ok_flag(&v),
            result_json: v.to_string(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(SimpleResult {
            success: false,
            result_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn daemon_cancel(state: State<'_, AppState>, app: AppHandle) -> Result<SimpleResult, String> {
    let rid = state.active_request.lock().await.clone();
    match daemon_call(
        &app,
        &state,
        "cancel",
        json!({ "request_id": rid }),
        false,
        10,
    )
    .await
    {
        Ok(v) => Ok(SimpleResult {
            success: ok_flag(&v),
            result_json: v.to_string(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(SimpleResult {
            success: false,
            result_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn transcribe(
    app: AppHandle,
    state: State<'_, AppState>,
    audio_path: String,
    backend: Option<String>,
) -> Result<TranscribeResult, String> {
    let backend = backend
        .filter(|b| !b.is_empty())
        .unwrap_or_else(|| "moss".to_string());
    let params = json!({
        "audio_path": audio_path,
        "backend": backend,
        "device": "auto",
    });
    match daemon_call(&app, &state, "transcribe", params, true, 3600).await {
        Ok(v) if ok_flag(&v) => {
            let entry_id = v
                .get("entry_id")
                .and_then(|x| x.as_str())
                .map(|s| s.to_string());
            let output = if let Some(tx) = v.get("transcript") {
                json!({
                    "meta": {"id": entry_id},
                    "transcript": tx,
                    "key_points": v.get("key_points"),
                    "entry_id": entry_id,
                })
                .to_string()
            } else {
                v.to_string()
            };
            Ok(TranscribeResult {
                success: true,
                output,
                entry_id,
                error: None,
            })
        }
        Ok(v) => Ok(TranscribeResult {
            success: false,
            output: v.to_string(),
            entry_id: None,
            error: err_msg(&v),
        }),
        Err(e) => Ok(TranscribeResult {
            success: false,
            output: String::new(),
            entry_id: None,
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn record(
    app: AppHandle,
    state: State<'_, AppState>,
    duration: Option<u64>,
) -> Result<RecordResult, String> {
    let params = json!({ "duration": duration.unwrap_or(30) });
    match daemon_call(&app, &state, "record", params, true, 600).await {
        Ok(v) if ok_flag(&v) => Ok(RecordResult {
            success: true,
            wav_path: v
                .get("wav_path")
                .and_then(|x| x.as_str())
                .map(|s| s.to_string()),
            error: None,
        }),
        Ok(v) => Ok(RecordResult {
            success: false,
            wav_path: None,
            error: err_msg(&v),
        }),
        Err(e) => Ok(RecordResult {
            success: false,
            wav_path: None,
            error: Some(e),
        }),
    }
}

/// Interactive recording control for hotkeys: start | pause | resume | stop | cancel | status
#[tauri::command]
async fn record_control(
    app: AppHandle,
    state: State<'_, AppState>,
    action: String,
) -> Result<SimpleResult, String> {
    let cmd = match action.as_str() {
        "start" => "record_start",
        "pause" => "record_pause",
        "resume" => "record_resume",
        "stop" => "record_stop",
        "cancel" => "record_cancel",
        "status" => "record_status",
        other => {
            return Ok(SimpleResult {
                success: false,
                result_json: "{}".into(),
                error: Some(format!("Unknown record action: {}", other)),
            });
        }
    };
    let timeout = if cmd == "record_stop" { 60 } else { 15 };
    match daemon_call(&app, &state, cmd, json!({}), false, timeout).await {
        Ok(v) => Ok(SimpleResult {
            success: ok_flag(&v),
            result_json: v.to_string(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(SimpleResult {
            success: false,
            result_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn history_list(
    app: AppHandle,
    state: State<'_, AppState>,
    limit: Option<u32>,
    person: Option<String>,
) -> Result<HistoryListResult, String> {
    let params = json!({
        "limit": limit.unwrap_or(100),
        "person": person.unwrap_or_default(),
    });
    match daemon_call(&app, &state, "history_list", params, false, 60).await {
        Ok(v) if ok_flag(&v) => {
            let entries = v.get("entries").cloned().unwrap_or(Value::Array(vec![]));
            Ok(HistoryListResult {
                success: true,
                entries_json: entries.to_string(),
                error: None,
            })
        }
        Ok(v) => Ok(HistoryListResult {
            success: false,
            entries_json: "[]".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(HistoryListResult {
            success: false,
            entries_json: "[]".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn history_get(
    app: AppHandle,
    state: State<'_, AppState>,
    entry_id: String,
) -> Result<HistoryEntryResult, String> {
    let params = json!({ "entry_id": entry_id });
    match daemon_call(&app, &state, "history_get", params, false, 60).await {
        Ok(v) if ok_flag(&v) => Ok(HistoryEntryResult {
            success: true,
            entry_json: v
                .get("entry")
                .map(|x| x.to_string())
                .unwrap_or_else(|| "{}".into()),
            transcript_text: v
                .get("transcript_text")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string(),
            analysis_text: v
                .get("analysis_text")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string(),
            audio_path: v
                .get("audio_path")
                .and_then(|x| x.as_str())
                .map(|s| s.to_string()),
            segments_json: v
                .get("segments")
                .map(|x| x.to_string())
                .unwrap_or_else(|| "[]".into()),
            error: None,
        }),
        Ok(v) => Ok(HistoryEntryResult {
            success: false,
            entry_json: "{}".into(),
            transcript_text: String::new(),
            analysis_text: String::new(),
            audio_path: None,
            segments_json: "[]".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(HistoryEntryResult {
            success: false,
            entry_json: "{}".into(),
            transcript_text: String::new(),
            analysis_text: String::new(),
            audio_path: None,
            segments_json: "[]".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn diary_search(
    app: AppHandle,
    state: State<'_, AppState>,
    query: String,
    person: Option<String>,
    limit: Option<u32>,
) -> Result<SearchResult, String> {
    let params = json!({
        "query": query,
        "person": person.unwrap_or_default(),
        "limit": limit.unwrap_or(50),
    });
    match daemon_call(&app, &state, "search", params, false, 120).await {
        Ok(v) if ok_flag(&v) => Ok(SearchResult {
            success: true,
            hits_json: v
                .get("hits")
                .map(|x| x.to_string())
                .unwrap_or_else(|| "[]".into()),
            error: None,
        }),
        Ok(v) => Ok(SearchResult {
            success: false,
            hits_json: "[]".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(SearchResult {
            success: false,
            hits_json: "[]".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn speakers_rename(
    app: AppHandle,
    state: State<'_, AppState>,
    entry_id: String,
    mapping_json: String,
    remember: Option<bool>,
) -> Result<RenameResult, String> {
    let mapping: Value =
        serde_json::from_str(&mapping_json).unwrap_or_else(|_| json!({}));
    let params = json!({
        "entry_id": entry_id,
        "mapping": mapping,
        "remember": remember.unwrap_or(true),
    });
    match daemon_call(&app, &state, "speakers_rename", params, false, 30).await {
        Ok(v) if ok_flag(&v) => Ok(RenameResult {
            success: true,
            speaker_map_json: v
                .get("speaker_map")
                .map(|x| x.to_string())
                .unwrap_or_else(|| "{}".into()),
            error: None,
        }),
        Ok(v) => Ok(RenameResult {
            success: false,
            speaker_map_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(RenameResult {
            success: false,
            speaker_map_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn export_entry_cmd(
    app: AppHandle,
    state: State<'_, AppState>,
    entry_id: String,
    formats: Option<String>,
) -> Result<ExportCmdResult, String> {
    let params = json!({
        "entry_id": entry_id,
        "formats": formats.unwrap_or_else(|| "md,srt,txt,json".to_string()),
    });
    match daemon_call(&app, &state, "export", params, false, 60).await {
        Ok(v) if ok_flag(&v) => Ok(ExportCmdResult {
            success: true,
            result_json: v.to_string(),
            error: None,
        }),
        Ok(v) => Ok(ExportCmdResult {
            success: false,
            result_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(ExportCmdResult {
            success: false,
            result_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn digest_cmd(
    app: AppHandle,
    state: State<'_, AppState>,
    days: Option<u32>,
) -> Result<DigestCmdResult, String> {
    let params = json!({ "days": days.unwrap_or(7) });
    match daemon_call(&app, &state, "digest", params, false, 120).await {
        Ok(v) if ok_flag(&v) => Ok(DigestCmdResult {
            success: true,
            markdown: v
                .get("markdown")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string(),
            path: v
                .get("path")
                .and_then(|x| x.as_str())
                .map(|s| s.to_string()),
            error: None,
        }),
        Ok(v) => Ok(DigestCmdResult {
            success: false,
            markdown: String::new(),
            path: None,
            error: err_msg(&v),
        }),
        Err(e) => Ok(DigestCmdResult {
            success: false,
            markdown: String::new(),
            path: None,
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn actions_inbox(
    app: AppHandle,
    state: State<'_, AppState>,
    include_done: Option<bool>,
) -> Result<RosterResult, String> {
    let params = json!({
        "include_done": include_done.unwrap_or(false),
        "sync": true,
    });
    match daemon_call(&app, &state, "actions_inbox", params, false, 60).await {
        Ok(v) if ok_flag(&v) => Ok(RosterResult {
            success: true,
            roster_json: v.to_string(),
            error: None,
        }),
        Ok(v) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn actions_done(
    app: AppHandle,
    state: State<'_, AppState>,
    action_id: String,
    done: Option<bool>,
) -> Result<RosterResult, String> {
    let params = json!({
        "action_id": action_id,
        "done": done.unwrap_or(true),
    });
    match daemon_call(&app, &state, "actions_done", params, false, 30).await {
        Ok(v) if ok_flag(&v) => Ok(RosterResult {
            success: true,
            roster_json: v
                .get("item")
                .map(|x| x.to_string())
                .unwrap_or_else(|| v.to_string()),
            error: None,
        }),
        Ok(v) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn entry_annotate(
    app: AppHandle,
    state: State<'_, AppState>,
    entry_id: String,
    add_tags: Option<String>,
    note: Option<String>,
    star: Option<bool>,
) -> Result<RosterResult, String> {
    let params = json!({
        "entry_id": entry_id,
        "add_tags": add_tags.unwrap_or_default(),
        "note": note.unwrap_or_default(),
        "star": star,
    });
    match daemon_call(&app, &state, "entry_annotate", params, false, 30).await {
        Ok(v) if ok_flag(&v) => Ok(RosterResult {
            success: true,
            roster_json: v
                .get("entry")
                .map(|x| x.to_string())
                .unwrap_or_else(|| "{}".into()),
            error: None,
        }),
        Ok(v) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn speakers_roster(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<RosterResult, String> {
    match daemon_call(&app, &state, "speakers_roster", json!({}), false, 30).await {
        Ok(v) if ok_flag(&v) => Ok(RosterResult {
            success: true,
            roster_json: v
                .get("roster")
                .map(|x| x.to_string())
                .unwrap_or_else(|| "{}".into()),
            error: None,
        }),
        Ok(v) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(RosterResult {
            success: false,
            roster_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn entry_archive(
    app: AppHandle,
    state: State<'_, AppState>,
    entry_id: String,
    unarchive: Option<bool>,
) -> Result<SimpleResult, String> {
    let params = json!({
        "entry_id": entry_id,
        "unarchive": unarchive.unwrap_or(false),
    });
    match daemon_call(&app, &state, "entry_archive", params, false, 30).await {
        Ok(v) if ok_flag(&v) => Ok(SimpleResult {
            success: true,
            result_json: v
                .get("entry")
                .map(|x| x.to_string())
                .unwrap_or_else(|| v.to_string()),
            error: None,
        }),
        Ok(v) => Ok(SimpleResult {
            success: false,
            result_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(SimpleResult {
            success: false,
            result_json: "{}".into(),
            error: Some(e),
        }),
    }
}

#[tauri::command]
async fn entry_delete(
    app: AppHandle,
    state: State<'_, AppState>,
    entry_id: String,
    delete_audio: Option<bool>,
) -> Result<SimpleResult, String> {
    let params = json!({
        "entry_id": entry_id,
        "delete_audio": delete_audio.unwrap_or(false),
    });
    match daemon_call(&app, &state, "entry_delete", params, false, 30).await {
        Ok(v) if ok_flag(&v) => Ok(SimpleResult {
            success: true,
            result_json: v.to_string(),
            error: None,
        }),
        Ok(v) => Ok(SimpleResult {
            success: false,
            result_json: "{}".into(),
            error: err_msg(&v),
        }),
        Err(e) => Ok(SimpleResult {
            success: false,
            result_json: "{}".into(),
            error: Some(e),
        }),
    }
}

fn main() {
    let _ = Path::new(".");
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .setup(|app| {
            // Warm daemon in background so first STT is faster
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let state = handle.state::<AppState>();
                match ensure_daemon(state.inner()).await {
                    Ok(ep) => {
                        eprintln!(
                            "[omniflow] daemon ready at {}:{}",
                            ep.host, ep.port
                        );
                    }
                    Err(e) => {
                        eprintln!("[omniflow] daemon not ready yet: {}", e);
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            transcribe,
            record,
            record_control,
            history_list,
            history_get,
            diary_search,
            export_entry_cmd,
            digest_cmd,
            speakers_rename,
            speakers_roster,
            actions_inbox,
            actions_done,
            entry_annotate,
            entry_archive,
            entry_delete,
            daemon_status,
            daemon_cancel,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
