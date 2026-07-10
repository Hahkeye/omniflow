# Omniflow

Omniflow is a multimodal diary application that uses speech recognition, audio diarization, and topic analysis to automatically create structured daily journals from spoken or recorded audio.

## Quick Start

1. Clone the repo
2. Set up the diary app backend
3. Record and transcribe audio
4. Analyze the transcripts

## Components

### `diary_app/` — Python CLI Backend

The core application that provides:

- **Recording**: Capture audio from microphone or file (via `sounddevice`/`pyaudio`)
- **Transcription**: Multi-backend speech recognition
  - **Nemo backend** (GPU, recommended): Uses Parakeet 0.6B multitalker ASR + Sortformer diarization
  - **Whisper backend** (CPU/Win/Linux/Mac): Uses whisperX + pyannote diarization
  - **Moss backend** (GPU): Uses MOSS-Transcribe-Diarize
- **Analysis**: Topic detection, key points extraction, speaker statistics
- **Output**: Structured JSON transcripts saved to `~/diary/`

#### Installation

```bash
pip install -r diary_app/requirements.txt
```

#### Usage

```bash
# Record audio (defaults to 30 seconds)
python3 -m diary_app record --duration 30

# Transcribe a WAV file
python3 -m diary_app transcribe recording.wav

# Transcribe and analyze
python3 -m diary_app analyze recording.wav

# Use specific backend
python3 -m diary_app transcribe recording.wav --backend nemo

# Specify output directory
python3 -m diary_app record --output /path/to/output
```

#### Dependencies

- **Nemo backend** (GPU): NVIDIA GPU with CUDA, NeMo toolkit
- **Whisper backend** (CPU/Win/Linux/Mac): whisperX, pyannote.audio, torch
- **Moss backend** (GPU): MOSS-Transcribe-Diarize

### `diary-frontend/` — Tauri Desktop App

A desktop application built with React frontend + Rust backend, providing:

- **Record**: Start/stop audio recording via microphone
- **Transcribe**: Upload and transcribe audio files
- **Analyze**: View topic analysis and key points from transcripts

#### Installation

```bash
# Install dependencies
pnpm install

# For development
pnpm tauri dev

# For production build
pnpm tauri build
```

#### Windows Build

To build the Tauri app for Windows:

1. Install prerequisites:
   - Visual Studio Build Tools (C++ build tools required)
   - Rust with MSVC target: `rustup target add x86_64-pc-windows-msvc`
   - Node.js/pnpm
2. Navigate to the frontend directory:
   ```bash
   cd diary-frontend
   ```
3. Install dependencies:
   ```bash
   pnpm install
   ```
4. Build for Windows:
   ```bash
   pnpm tauri build --target x86_64-pc-windows-msvc
   ```
5. The built `.exe` will be in `diary-frontend/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/msi/Diary_0.1.0_x64_en-US.msi`

#### Linux Build (from WSL)

```bash
cd diary-frontend
pnpm install
pnpm tauri build
```

Bundles will be in `diary-frontend/src-tauri/target/release/bundle/`

## Project Structure

```
omniflow/
├── diary_app/           # Python CLI backend
│   ├── core/            # Core modules (backends, analysis)
│   ├── ui/              # Terminal UI components
│   └── main.py          # CLI entry point
├── diary-frontend/      # Tauri desktop app
│   ├── src/             # React frontend
│   └── src-tauri/       # Rust backend (Tauri)
└── README.md
```

## License

MIT
