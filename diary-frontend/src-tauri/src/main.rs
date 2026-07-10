#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::fs;

#[derive(Deserialize)]
struct TranscribeArgs {
    audio_path: String,
}

#[derive(Serialize)]
struct TranscribeResult {
    success: bool,
    output: String,
    error: Option<String>,
}

#[derive(Deserialize)]
struct RecordArgs {
    #[serde(default = "default_duration")]
    duration: u64,
}

fn default_duration() -> u64 {
    30
}

#[derive(Serialize)]
struct RecordResult {
    success: bool,
    wav_path: Option<String>,
    error: Option<String>,
}

#[tauri::command]
async fn transcribe(args: TranscribeArgs) -> Result<TranscribeResult, String> {
    let audio_path = &args.audio_path;
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".to_string());
    let project_root = Path::new(&home).join("code/omniflow");
    let output_dir = Path::new(&home).join("diary/tmp");
    let _ = fs::create_dir_all(&output_dir).await.map_err(|e| format!("Failed to create output dir: {}", e))?;

    let cmd = tokio::process::Command::new("python3")
        .arg("-m").arg("diary_app").arg("transcribe")
        .arg(audio_path).arg("--backend").arg("moss")
        .arg("--output").arg(output_dir.join("transcript.json"))
        .current_dir(&project_root)
        .output().await
        .map_err(|e| format!("Failed to execute: {}", e))?;

    if !cmd.status.success() {
        return Ok(TranscribeResult { success: false, output: String::from_utf8_lossy(&cmd.stdout).to_string(), error: Some(String::from_utf8_lossy(&cmd.stderr).to_string()) });
    }

    // Read the transcript JSON file directly
    let json_path = output_dir.join("transcript.json");
    let json_content = fs::read_to_string(&json_path).await.map_err(|e| format!("Failed to read: {}", e))?;

    Ok(TranscribeResult { success: true, output: json_content, error: None })
}

#[tauri::command]
async fn record(args: RecordArgs) -> Result<RecordResult, String> {
    let duration = args.duration;
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".to_string());
    let project_root = Path::new(&home).join("code/omniflow");
    let output_dir = Path::new(&home).join("diary/tmp");
    let _ = fs::create_dir_all(&output_dir).await.map_err(|e| format!("Failed to create output dir: {}", e))?;

    // Run the record CLI first
    let cmd = tokio::process::Command::new("python3")
        .arg("-m").arg("diary_app").arg("record")
        .arg("--duration").arg(format!("{}", duration))
        .arg("--output").arg(&output_dir)
        .current_dir(&project_root)
        .output().await
        .map_err(|e| format!("Failed to execute: {}", e))?;

    if !cmd.status.success() {
        return Ok(RecordResult { success: false, wav_path: None, error: Some(String::from_utf8_lossy(&cmd.stderr).to_string()) });
    }

    // Find newest recording_*.wav after CLI succeeds (Python uses datetime format, not unix timestamp)
    let mut entries = fs::read_dir(&output_dir).await.map_err(|e| format!("Failed to read dir: {}", e))?;
    let mut latest: Option<tokio::fs::DirEntry> = None;
    while let Some(entry) = entries.next_entry().await.map_err(|e| format!("Failed to read entry: {}", e))? {
        if let Some(name) = entry.file_name().to_str() {
            if name.starts_with("recording_") && name.ends_with(".wav") {
                if latest.is_none() || entry.metadata().await.unwrap().modified().unwrap() > latest.as_ref().unwrap().metadata().await.unwrap().modified().unwrap() {
                    latest = Some(entry);
                }
            }
        }
    }
    
    let wav_path = latest.ok_or("No recording file found")?.path();
    Ok(RecordResult { success: true, wav_path: Some(wav_path.to_str().unwrap().to_string()), error: None })
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![transcribe, record])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}