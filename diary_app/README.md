# Diary Transcript

Record audio, transcribe multi-speaker conversations with diarization, and extract key points / takeaways.

**Default model (Mac + PC):** [OpenMOSS-Team/MOSS-Transcribe-Diarize](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize) — end-to-end ASR + speaker diarization in one pass.

## Requirements

- Python 3.12+ recommended
- **Mac (Apple Silicon or Intel):** CPU or MPS via PyTorch
- **PC:** CPU, or NVIDIA CUDA for faster inference
- ffmpeg optional (only needed for non-WAV inputs with some backends)

## Installation (multi-architecture)

**Recommended** — detects OS/arch/GPU and installs the correct torch wheels first
(so a later `pip install` does not clobber CUDA with a CPU build):

```bash
cd /path/to/omniflow
bash diary_app/setup_venv.sh
source .venv/bin/activate
python -m diary_app doctor
```

Windows PowerShell:

```powershell
.\diary_app\install.ps1
.\.venv\Scripts\Activate.ps1
python -m diary_app doctor
```

### Manual two-step

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m diary_app.install_torch          # arch-correct torch + torchaudio
pip install -e ".[dev]"                    # core package (torch not re-pinned)
# equivalent core deps: pip install -r diary_app/requirements-core.txt
```

| Host | Torch source |
|------|----------------|
| macOS arm64 / x86_64 | PyPI default |
| Linux x86_64 + NVIDIA | `https://download.pytorch.org/whl/cu128` |
| Linux x86_64 CPU | `…/whl/cpu` |
| Linux aarch64 | PyPI (CPU); Jetson/CUDA = vendor wheels |
| Windows x86_64 + NVIDIA | `…/whl/cu128` |
| Windows x86_64 CPU | `…/whl/cpu` |

```bash
OMNIFLOW_TORCH=cpu bash diary_app/setup_venv.sh
OMNIFLOW_TORCH=cuda OMNIFLOW_CUDA_CHANNEL=cu126 bash diary_app/setup_venv.sh
python -m diary_app.install_torch --flavor cuda --cuda-channel cu128
python -m diary_app.install_torch --dry-run   # print plan only
```

**Important:** Do not editable-install `moss-transcribe-diarize` under `/tmp`.  
Do not `pip install torch` from bare PyPI on Linux NVIDIA boxes — use `install_torch`.

### Optional backends

```bash
# WhisperX (+ optional pyannote diarization with HF_TOKEN)
pip install -r diary_app/requirements-whisper.txt

# NeMo multitalker (NVIDIA CUDA only — not for Mac)
pip install -r diary_app/requirements-nemo.txt

# Gradio UI
pip install -r diary_app/requirements-ui.txt
```

## Usage

### GPU / device detection

```bash
# Show CUDA / MPS / CPU status and what --device auto would pick
python3 -m diary_app devices
```

Auto device order: **CUDA (NVIDIA) → MPS (Apple Silicon) → CPU**.

```bash
# Use GPU if available (default)
python3 -m diary_app transcribe recording.wav --device auto

# Force NVIDIA GPU
python3 -m diary_app transcribe recording.wav --device cuda
python3 -m diary_app transcribe recording.wav --device cuda:0

# Force CPU
python3 -m diary_app transcribe recording.wav --device cpu
```

If you have an NVIDIA GPU but `devices` shows CPU-only torch, install a CUDA build:

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
```

### File-based transcription (recommended in WSL / headless)

```bash
# Auto backend (moss → whisper → nemo), auto device (CUDA if available)
python3 -m diary_app transcribe recording.wav

# Explicit MOSS (recommended Mac + PC)
python3 -m diary_app transcribe recording.wav --backend moss --device auto

# Whisper fallback
python3 -m diary_app transcribe recording.wav --backend whisper

# Save JSON + show full transcript
python3 -m diary_app transcribe recording.wav --output ~/diary/out.json --show-transcript
```

### Analyze an existing transcript

```bash
python3 -m diary_app analyze --file ~/diary/transcript_....json
```

### Full diary workflow (microphone)

```bash
python3 -m diary_app diary
python3 -m diary_app diary --backend moss --duration 120
python3 -m diary_app diary --file recording.wav --show-transcript
python3 -m diary_app diary --silence-stop
```

### History (browse past sessions)

```bash
# List newest-first (transcripts + audio when available)
python3 -m diary_app history
python3 -m diary_app list          # same idea, shorter

# Open one entry (transcript + analysis + paths)
python3 -m diary_app history --id 20260709_181713

# Play linked audio with a system player
python3 -m diary_app history --id 20260709_181713 --play
```

### Tags, notes & stars

```bash
python3 -m diary_app tag --id 20260709_181713 --add meeting project-x --star
python3 -m diary_app tag --id 20260709_181713 --note "Follow up with design"
python3 -m diary_app tag --list-tags
python3 -m diary_app tag --filter-tag meeting
python3 -m diary_app tag --starred
```

### Action inbox

```bash
python3 -m diary_app actions list          # sync + list open todos
python3 -m diary_app actions done a_abc123
python3 -m diary_app actions add "Call the vendor" --entry 20260709_181713
python3 -m diary_app actions sync
```

Stored in `~/diary/actions.json`. Completing an item keeps it done across digests.

### Transcription resilience

If MOSS returns text that is not timed/diarized (e.g. `[Music]`), the raw output is kept on the transcript, warnings are printed, and non-empty raw text is stored so history/search still see it.

History listing uses an **in-process index cache** (auto-invalidated on writes) for faster search/list on WSL.

### Export (Markdown / SRT / TXT / JSON)

```bash
# Latest entry → ~/diary/exports/<id>/
python3 -m diary_app export

# Specific entry / formats
python3 -m diary_app export --id 20260709_181713 --formats md,srt
python3 -m diary_app export --id 20260709_181713 --output ~/Desktop/diary-out
```

Creates a folder with diary-style Markdown (summary, decisions, action items, transcript),
SRT subtitles for video tools, plain text, and a full JSON bundle.

### Daily / weekly digest

```bash
python3 -m diary_app digest              # last 7 active days
python3 -m diary_app digest --days 14
python3 -m diary_app digest --start 2026-07-01 --end 2026-07-15
python3 -m diary_app digest --no-save    # print only
```

Rolls up sessions per day: speakers, topics, **decisions**, **action items**, key points.
Saved under `~/diary/exports/digest_*.md`.

### Action items & decisions

Automatic heuristic extraction runs with every analysis (no API key required):

- **Decisions** — “we decided / agreed / let’s go with …”
- **Action items** — “we need to / I’ll / follow up / by Friday …”

Shown in CLI results, analysis JSON, Markdown export, and digests.

### Search + click-to-seek

```bash
# Full-text search (transcripts, titles, analysis)
python3 -m diary_app search budget
python3 -m diary_app search "next week" --speaker Alex

# Play first hit audio from the matching segment time (ffplay/mpv)
python3 -m diary_app search hands --seek

# Open first match in history view
python3 -m diary_app search hands --open
```

In the Gradio **Search** tab and Tauri **Search** view, pick a hit then **click a segment** to seek the audio player to that timestamp. History also lists all segments as click-to-seek rows.

### Speaker naming + memory

Anonymous labels (`Speaker 1`, `S01`) can be renamed to real people. Names are stored per entry and optionally remembered for future sessions.

```bash
# Rename on one entry and remember defaults (Speaker 1 → Me next time)
python3 -m diary_app history --id 20260709_181713 \
  --rename 'Speaker 1=Me' 'Speaker 2=Alex' --remember

# Filter history by person
python3 -m diary_app history --speaker Alex

# Roster of known people
python3 -m diary_app speakers list
python3 -m diary_app speakers add Sam
python3 -m diary_app speakers remove Sam
python3 -m diary_app speakers clear-defaults
```

Storage under `~/diary/`:

- `speakers.json` — known people + remembered `Speaker N → name` defaults
- `entries/<id>.json` — includes `speaker_map`
- `transcript_<id>.json` — `meta.speaker_map` for display

New transcriptions are saved as linked history entries under `~/diary/`:

- `entries/<id>.json` — index record
- `transcript_<id>.json` — segments + metadata (including `audio_path`)
- `analysis_<id>.json` — key points / takeaways
- `recording_*.wav` — audio when recorded

Legacy loose files are still discovered and shown.

### Gradio UI

```bash
pip install -r diary_app/requirements-ui.txt
python3 -m diary_app.ui.app
# → http://127.0.0.1:7860
```

## Backends

| Backend | Platforms | Diarization | Notes |
|---------|-----------|-------------|--------|
| **moss** (default) | Mac + PC (CPU/MPS/CUDA) | Yes (built-in) | Same HF model everywhere |
| whisper | Mac + PC | Optional via pyannote + `HF_TOKEN` | Fallback |
| nemo | Linux/Windows + CUDA | Yes | Optional, experimental |

## Outputs

Transcripts and analysis are saved under `~/diary/` as JSON:

- Speaker segments (`speaker`, `start` / `start_time`, `end` / `end_time`, `text`)
- Speaker statistics
- Topics, key points, takeaways

## Limitations

- **WSL:** usually no mic — use `transcribe <file>`.
- **Long audio:** MOSS generation budget scales with duration; very long meetings need more RAM/VRAM.
- **NeMo:** CUDA only; not used on Mac.
- **Whisper diarization:** needs `HF_TOKEN` and accepting pyannote model terms on Hugging Face.

## JSON API & local daemon (product IPC)

**One-shot API** (scripts, debugging):

```bash
python -m diary_app api history_list --set limit=20
python -m diary_app api transcribe --json '{"audio_path":"x.wav","backend":"moss"}'
```

**Long-lived daemon** (desktop / warm models) — preferred for the Tauri app:

```bash
python -m diary_app serve --detach          # start in background
python -m diary_app daemon status
python -m diary_app daemon ensure           # start if not running
python -m diary_app daemon stop
```

State: `~/diary/daemon.json` (host, port, pid, token).  
Protocol: NDJSON lines on `127.0.0.1:17432` with token auth; progress events stream on the same connection.

```bash
python -m diary_app reindex
python -m diary_app archive --id <id>
python -m diary_app delete --id <id> --yes
```

## Optional encryption

```bash
export DIARY_KEY="$(python -c 'from diary_app.core.crypto import generate_key; print(generate_key())')"
export DIARY_ENCRYPT=1
```

## Architecture

```
diary_app/
├── config.py               # AppConfig (toml + env)
├── domain/                 # models + ports
├── services/               # pipeline use-cases
├── cli/                    # thin CLI → services
├── main.py                 # argparse entry
├── core/
│   ├── api.py / daemon.py  # IPC
│   ├── store.py            # EntryStore
│   ├── registry.py         # backends + analyzers
│   ├── history.py / index_db.py
│   ├── moss_backend.py …
│   └── analyzer.py         # HeuristicAnalyzer
└── ui/                     # Gradio (secondary)
```

```bash
python -m diary_app config show
python -m diary_app config write-example
```
