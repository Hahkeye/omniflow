# Omniflow

**Desktop diary app** for spoken and recorded audio: speech recognition, speaker diarization, and structured notes (topics, decisions, action items).

**Product surface:** the **Tauri GUI** (Diary).  
**Behind the scenes:** a local Python daemon keeps STT models warm and owns your data under `~/diary/` (Windows: `%USERPROFILE%\diary\`).

**Default STT model (Mac + PC):** [MOSS-Transcribe-Diarize 0.9B](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize)

**Repository:** [github.com/Hahkeye/omniflow](https://github.com/Hahkeye/omniflow)

---

## Quick start — open the app (Mac / Windows / Linux)

Goal: clone → **one script** installs missing host tools + Omniflow runtime → **Diary opens**.

### Easiest path (recommended)

**Windows (PowerShell)** — needs [winget](https://learn.microsoft.com/windows/package-manager/winget/) (comes with modern Win10/11):

```powershell
# If scripts are blocked for this session:
Set-ExecutionPolicy -Scope Process Bypass

git clone https://github.com/Hahkeye/omniflow.git
cd omniflow

# Installs Git/Python/Node/Rust if missing, creates .venv, launches Diary
.\scripts\get-started.ps1 -CpuOnly

# First compile on a clean PC (adds VS C++ Build Tools — large, once):
# .\scripts\get-started.ps1 -CpuOnly -WithBuildTools
```

**macOS / Linux**

```bash
git clone https://github.com/Hahkeye/omniflow.git
cd omniflow

# Uses brew / apt / dnf + rustup when possible
OMNIFLOW_TORCH=cpu bash scripts/get-started.sh

# macOS without Xcode CLT yet:
# bash scripts/get-started.sh --with-xcode
```

What `get-started` does for you:

1. **`bootstrap-tools`** — Git, Python 3.12, Node LTS, pnpm, Rust (rustup)  
2. **`launch-diary -Setup`** — Omniflow `.venv` + torch + deps, then `pnpm tauri dev`

You still need a working package manager (`winget` / Homebrew / apt) and network.  
**Windows first Tauri compile** needs C++ build tools once; pass `-WithBuildTools` or install [VS Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) manually.

### Later sessions (already installed)

```bash
bash scripts/launch-diary.sh
```

```powershell
.\scripts\launch-diary.ps1
```

Missing tools are auto-detected and bootstrap is re-run when needed.

### Optional: CUDA / CPU / tools-only

```bash
# CUDA (Linux / Windows NVIDIA)
OMNIFLOW_TORCH=cuda OMNIFLOW_CUDA_CHANNEL=cu128 bash scripts/get-started.sh

# Tools only (no app launch)
bash scripts/bootstrap-tools.sh --status
bash scripts/bootstrap-tools.sh --yes
```

```powershell
$env:OMNIFLOW_TORCH = 'cuda'
$env:OMNIFLOW_CUDA_CHANNEL = 'cu128'
.\scripts\get-started.ps1

.\scripts\bootstrap-tools.ps1 -Status
.\scripts\bootstrap-tools.ps1 -Yes -WithBuildTools
```

First Rust compile can take several minutes. When the window opens, use **Record** (or import audio) — the app starts the Python daemon automatically.

### 3. If something fails

```bash
# Activate venv first if needed
source .venv/bin/activate          # macOS / Linux
# .\.venv\Scripts\Activate.ps1   # Windows

python -m diary_app doctor
python -m diary_app devices
python -m diary_app daemon status
```

| Symptom | Try |
|---------|-----|
| doctor fails / no torch | `python -m diary_app.install_torch` or re-run launch with `--setup` / `-Setup` |
| UI opens, STT errors | Confirm `.venv` exists; launch script sets `DIARY_PYTHON` — use the script, not bare `pnpm tauri dev` without env |
| No mic | Transcribe a file from the UI, or fix OS mic permissions |
| CUDA not used | Re-install with `OMNIFLOW_TORCH=cuda` |

Production bundle (optional):

```bash
bash scripts/launch-diary.sh --build
# .\scripts\launch-diary.ps1 -Build
```

> **Shipping note:** The desktop app is not fully self-contained yet. It needs this checkout (or `diary_app/` on disk) and a Python 3.11+ env. The launch scripts wire that for development. A true single-installer ship is future work.

---

## How the product is layered

```
┌─────────────────────────────────────┐
│  Diary (Tauri + React)              │  ← you use this
│  record · history · search · …      │
└──────────────┬──────────────────────┘
               │ NDJSON over localhost TCP
┌──────────────▼──────────────────────┐
│  Python daemon (models stay warm)   │  ← automatic
│  SessionService → STT → analyze     │
│  ~/diary/  (JSON + audio + index)   │
└─────────────────────────────────────┘
```

| Piece | Role |
|-------|------|
| **`diary-frontend/`** | Product GUI |
| **`diary_app/` daemon + API** | Hidden runtime |
| **CLI** (`python -m diary_app …`) | Install, doctor, automation, recovery — not the daily UI |
| **Gradio** | Optional browser demo only |

---

## CLI (toolkit — optional)

For power users, CI, and debugging. Full details: [diary_app/README.md](diary_app/README.md).

```bash
source .venv/bin/activate   # or Windows Activate.ps1

python -m diary_app doctor
python -m diary_app devices
python -m diary_app serve --detach
python -m diary_app daemon status
python -m diary_app transcribe path/to/audio.wav --backend moss --show-transcript
python -m diary_app history --limit 20
python -m diary_app reindex
```

### Manual runtime install (without launch script)

```bash
# macOS / Linux / WSL
bash diary_app/setup_venv.sh
source .venv/bin/activate

# Windows PowerShell
# .\diary_app\install.ps1
# .\.venv\Scripts\Activate.ps1
```

| Platform | Default torch |
|----------|----------------|
| macOS arm64 / x86_64 | PyPI (MPS when available) |
| Linux x86_64 + NVIDIA | CUDA (`cu128`) |
| Linux / Windows CPU | CPU wheels |
| Windows x86_64 + NVIDIA | CUDA wheels |

### JSON API & daemon (for scripts / desktop)

```bash
python -m diary_app api history_list --set limit=20
python -m diary_app api transcribe --json '{"audio_path":"/path/file.wav","backend":"moss"}'
python -m diary_app serve --detach
python -m diary_app daemon ensure
```

- **Protocol:** NDJSON on `127.0.0.1:17432` (token in `~/diary/daemon.json`)
- Progress streams as `type=progress`; Cancel is supported from the UI

---

## Privacy & encryption

- Diary data lives under `~/diary/` (JSON + audio). Treat it as sensitive.
- Optional at-rest encryption (Fernet):

```bash
python -c "from diary_app.core.crypto import generate_key; print(generate_key())"
export DIARY_KEY='...'
export DIARY_ENCRYPT=1
```

Encrypted files start with magic `OMNIFLOW1`.

---

## Gradio (secondary demo)

```bash
pip install -r diary_app/requirements-ui.txt
python -m diary_app.ui
# → http://127.0.0.1:7860
```

---

## Architecture

```
omniflow/
├── scripts/
│   ├── get-started.sh / .ps1       # one-shot: tools + venv + Diary
│   ├── bootstrap-tools.sh / .ps1   # Git/Python/Node/Rust (host)
│   └── launch-diary.sh / .ps1      # product entry (venv + Tauri)
├── diary-frontend/          # Tauri + React (product UI)
├── diary_app/
│   ├── services/            # pipeline + SessionService
│   ├── core/                # daemon, api, STT backends, history
│   ├── cli/                 # toolkit commands
│   └── ui/                  # Gradio (secondary)
├── tests/
└── pyproject.toml
```

**Config:** `~/.config/omniflow/config.toml` or `~/diary/config.toml`  
(`python -m diary_app config write-example`)

## Development

```bash
# Unit tests (no heavy ML download)
source .venv/bin/activate
pip install -e ".[dev]"   # if not already
pytest

# GUI
bash scripts/launch-diary.sh
```

## License

MIT — see [LICENSE](LICENSE).
