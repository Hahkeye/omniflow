# Omniflow

Omniflow is a multimodal diary application that uses speech recognition, speaker diarization, and topic analysis to create structured journals from spoken or recorded audio.

**Default STT model (Mac + PC):** [MOSS-Transcribe-Diarize 0.9B](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize) — joint transcription + diarization from one checkpoint.

**Repository:** [github.com/Hahkeye/omniflow](https://github.com/Hahkeye/omniflow)

## Clone → first transcript (Mac / Windows / Linux)

Follow this end-to-end checklist on a fresh machine. Goal: install deps, run health checks, then transcribe a WAV.

### Prerequisites

| Tool | Why | Notes |
|------|-----|--------|
| **Git** | Clone + install `moss-transcribe-diarize` (git dependency) | Required on all platforms |
| **Python 3.11+** | Runtime | 3.12 recommended |
| **Disk / network** | First model download from Hugging Face is large | Use a solid connection |
| **Microphone (optional)** | `record` command | Not needed for file transcription |
| **NVIDIA drivers + CUDA (optional)** | Faster PC inference | Skip on Mac; use CPU install if no GPU |

**macOS extras (Tauri only):** Xcode Command Line Tools (`xcode-select --install`), [Rust](https://rustup.rs/), [Node.js 20+](https://nodejs.org/), [pnpm](https://pnpm.io/).

**Windows extras (Tauri only):** [Visual Studio C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/), [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) (usually present on Win10/11), Rust, Node.js 20+, pnpm.

### 1. Clone

```bash
git clone https://github.com/Hahkeye/omniflow.git
cd omniflow
```

### 2. Bootstrap Python (pick your OS)

**macOS / Linux / WSL**

```bash
# Optional: use a specific interpreter
# PYTHON=python3.12 bash diary_app/setup_venv.sh

bash diary_app/setup_venv.sh
source .venv/bin/activate
```

**Windows (PowerShell)**

```powershell
# If scripts are blocked for this session:
# Set-ExecutionPolicy -Scope Process Bypass

.\diary_app\install.ps1
.\.venv\Scripts\Activate.ps1
```

Torch wheels differ by **OS + CPU arch + CUDA**. The bootstrap scripts install the correct torch **before** the rest of the package so a CPU wheel does not clobber a CUDA install.

| Platform | Arch | Default torch |
|----------|------|----------------|
| macOS | arm64 (Apple Silicon), x86_64 | PyPI (MPS when available) |
| Linux | x86_64 + NVIDIA | CUDA wheels (`cu128`) |
| Linux | x86_64, no GPU | CPU wheels |
| Linux | aarch64 | PyPI/CPU (vendor CUDA manual) |
| Windows | x86_64 + NVIDIA | CUDA wheels |
| Windows | x86_64, no GPU | CPU wheels |

```bash
# Force CPU or CUDA wheel selection (macOS / Linux)
OMNIFLOW_TORCH=cpu bash diary_app/setup_venv.sh
OMNIFLOW_TORCH=cuda OMNIFLOW_CUDA_CHANNEL=cu128 bash diary_app/setup_venv.sh

# Windows PowerShell equivalents
# $env:OMNIFLOW_TORCH='cpu'; .\diary_app\install.ps1
# $env:OMNIFLOW_TORCH='cuda'; $env:OMNIFLOW_CUDA_CHANNEL='cu128'; .\diary_app\install.ps1

# Or only reinstall torch
python -m diary_app.install_torch --dry-run
python -m diary_app.install_torch
```

### 3. Health checks

```bash
python -m diary_app doctor          # arch + torch health check
python -m diary_app devices         # CUDA / MPS / CPU
```

### 4. First transcript

Use any 16 kHz mono WAV (or let the pipeline convert common formats when deps allow):

```bash
python -m diary_app transcribe path/to/audio.wav --backend moss --show-transcript
```

Or record 15 seconds from the mic, then analyze:

```bash
python -m diary_app record --duration 15
python -m diary_app diary --backend auto
```

Diary JSON + audio land under `~/diary/` (Windows: `%USERPROFILE%\diary\`).

### 5. Optional — Tauri desktop shell

The shell talks to a long-lived Python daemon. Install the Python stack **first** (steps 1–3), then:

```bash
cd diary-frontend
pnpm install

# Point at this checkout + venv when paths are non-default
# macOS / Linux:
#   export DIARY_PROJECT_ROOT=/path/to/omniflow
#   export DIARY_PYTHON=/path/to/omniflow/.venv/bin/python
# Windows PowerShell:
#   $env:DIARY_PROJECT_ROOT = "C:\path\to\omniflow"
#   $env:DIARY_PYTHON = "C:\path\to\omniflow\.venv\Scripts\python.exe"

pnpm tauri dev      # development
pnpm tauri build    # platform installer / bundle
```

> **Shipping note:** The desktop app is not fully self-contained yet. It still needs this repo (or `diary_app/` on disk) and a Python 3.11+ env with Omniflow installed. Use `DIARY_PROJECT_ROOT` / `OMNIFLOW_ROOT` and `DIARY_PYTHON` / `PYTHON` when paths are non-default.
## Components

### `diary_app/` — Python CLI + library

- **Recording:** microphone capture via `sounddevice` (16 kHz mono WAV)
- **Transcription backends:**
  - **moss** (default, Mac + PC): `OpenMOSS-Team/MOSS-Transcribe-Diarize`
  - **whisper** (optional): WhisperX + optional pyannote diarization
  - **nemo** (optional, NVIDIA only): Parakeet multitalker
- **Analysis:** topics, key points, takeaways, decisions, action items
- **History:** `~/diary/` JSON entries, SQLite FTS index, tags/stars, archive/delete
- **JSON API:** stable IPC for UIs (`python -m diary_app api …`)

```bash
python3 -m diary_app record --duration 30
python3 -m diary_app transcribe recording.wav --backend moss
python3 -m diary_app analyze --file ~/diary/transcript_....json
python3 -m diary_app diary --backend auto
python3 -m diary_app reindex          # rebuild ~/diary/index.sqlite
python3 -m diary_app archive --id <id>
python3 -m diary_app delete --id <id> --yes
```

See [diary_app/README.md](diary_app/README.md) for platform install details and optional backends.

### JSON API (for Tauri / scripts)

All UI integrations should use this instead of scraping the filesystem:

```bash
python -m diary_app api history_list --set limit=20
python -m diary_app api history_get --json '{"entry_id":"20260803_120000_ab12cd"}'
python -m diary_app api search --json '{"query":"budget","limit":50}'
python -m diary_app api transcribe --json '{"audio_path":"/path/file.wav","backend":"moss"}'
```

Responses are a single JSON object on **stdout** (`{"ok": true, ...}`).  
Long jobs emit progress on **stderr** as `PROGRESS_JSON {...}` lines.

### Local daemon (product IPC)

Desktop and other clients talk to a **long-lived Python daemon** on localhost so STT models stay warm:

```bash
python -m diary_app serve --detach     # background
python -m diary_app daemon status
python -m diary_app daemon stop
python -m diary_app daemon ensure      # start if needed
```

- **Protocol:** NDJSON over TCP `127.0.0.1:17432` (auth token in `~/diary/daemon.json`)
- **Progress:** streaming `type=progress` lines during record/transcribe
- **Cancel:** `cancel` command (or Tauri **Cancel** button)
- **Warmup:** models load once and remain in-process

CLI one-shots still work via `python -m diary_app api …` without the daemon.

### `diary-frontend/` — Tauri desktop shell

React + Rust **client** for the daemon (not a per-command process spawner).

On launch, Tauri ensures the daemon is running, then sends all commands over TCP with progress events.

Setup (prereqs, env vars, `pnpm tauri dev` / `build`) is in **[Clone → first transcript](#clone--first-transcript-mac--windows--linux)** step 5. The app is not fully self-contained yet: it needs this checkout + a Python env with Omniflow installed.

## Privacy & encryption

- Diary data lives under `~/diary/` (JSON + audio). Treat it as sensitive.
- **Optional at-rest encryption** (Fernet) for JSON writes:

```bash
# Generate a key and store it
python -c "from diary_app.core.crypto import generate_key; print(generate_key())"
export DIARY_KEY='...'          # Fernet key
export DIARY_ENCRYPT=1          # encrypt new writes
# or: python -m diary_app api crypto_status --set action=ensure_key_file
```

Encrypted files start with magic `OMNIFLOW1`. Without `DIARY_KEY`, encrypted files cannot be read.

## Gradio UI

```bash
pip install -r diary_app/requirements-ui.txt
python3 -m diary_app.ui
# → http://127.0.0.1:7860  (localhost only by default)
# DIARY_UI_HOST=0.0.0.0 to bind all interfaces (not recommended)
```

## Architecture (product layout)

```
omniflow/
├── diary_app/
│   ├── config.py              # AppConfig (file + env + defaults)
│   ├── domain/                # models + ports (no UI)
│   ├── services/              # pipeline: record→transcribe→analyze→persist
│   ├── cli/                   # thin CLI (session/history/tools) → SessionService
│   ├── services/
│   │   ├── pipeline.py        # record → STT → analyze → persist
│   │   └── session.py         # product facade + backend cache
│   ├── core/
│   │   ├── api.py             # JSON IPC → SessionService
│   │   ├── daemon.py          # long-lived localhost daemon
│   │   ├── store.py           # EntryStore (SQLite index + files)
│   │   ├── registry.py        # backend / analyzer plugins
│   │   ├── history.py         # file documents + index writes
│   │   └── moss_backend.py    # default STT (via registry only)
│   ├── main.py                # CLI entry + argparse
│   └── ui/                    # Gradio (secondary; uses SessionService)
├── diary-frontend/            # Tauri client of the daemon
├── tests/
└── pyproject.toml
```

**Config:** `~/.config/omniflow/config.toml` or `~/diary/config.toml`  
(`python -m diary_app config write-example`)

## Development

```bash
pip install -e ".[dev]"
pytest
python -m diary_app devices
```

## License

MIT — see [LICENSE](LICENSE).
