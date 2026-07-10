# Diary Transcript

Record audio, transcribe multi-speaker conversations, and extract key points.

## Requirements

- Python 3.12+
- NVIDIA GPU (RTX 40/50 series recommended) for NeMo backend
- OR CPU/Mac with whisper backend (no GPU required)
- ffmpeg (optional, only needed for non-WAV audio formats)

## Installation

```bash
pip install -r requirements.txt
```

For NVIDIA GPU backend (Linux with CUDA):
```bash
pip install -r requirements.txt
pip install 'nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@main'
```

## Usage

### File-based transcription (recommended for WSL/Linux without mic)

```bash
# Transcribe an existing audio file (auto-detects GPU → NeMo, else whisper)
python3 -m diary_app transcribe recording.wav

# Use whisper backend explicitly
python3 -m diary_app transcribe recording.wav --backend whisper

# Use Apple Silicon with medium model for better quality
python3 -m diary_app transcribe recording.wav --backend whisper --mps

# Save transcript and key points to custom output
python3 -m diary_app transcribe recording.wav --output /path/to/output

# Show full transcript in results
python3 -m diary_app transcribe recording.wav --show-transcript
```

### Analyze an existing transcript

```bash
# Analyze a transcript JSON file
python3 -m diary_app analyze transcript.json

# Save key points to custom output
python3 -m diary_app analyze transcript.json --output /path/to/output
```

### Full diary workflow (requires working microphone)

```bash
# Record → transcribe → analyze (auto-detect backend)
python3 -m diary_app diary

# Use whisper backend
python3 -m diary_app diary --backend whisper

# Use Apple Silicon medium model with full transcript display
python3 -m diary_app diary --backend whisper --mps --show-transcript

# Skip recording, transcribe existing file
python3 -m diary_app diary --file recording.wav

# Record with 5-minute duration limit
python3 -m diary_app diary --duration 300

# Stop recording after silence
python3 -m diary_app diary --silence-stop
```

### List recent recordings

```bash
python3 -m diary_app list
```

## Transcripts & Analysis

Transcripts are saved as JSON files with:
- Speaker segments (speaker label, start/end times, text)
- Speaker statistics (word count, percentage, duration, segments)
- Topics (from TF-IDF-like noun phrase scoring)
- Key points (sentence scoring for important content)
- Takeaways (summary of key insights)

Example analysis output:

```
📊 Results
  Speakers: 2
  Duration: 45s
  Segments: 12
  Output:   /path/to/recording.wav

👤 Speaker Statistics
  Speaker A: 120 words (45%), 22s, 6 segments
  Speaker B: 140 words (55%), 23s, 6 segments

## Limitations

- **WSL:** No microphone input available. Use `diary transcribe <file>` instead.
- **ffmpeg:** Not available without sudo. Audio must be in 16kHz mono WAV format (torchaudio can load WAV without ffmpeg).
- **NeMo:** Requires NVIDIA GPU and model download. Marked as experimental.

## Architecture

```
diary_app/
├── main.py              # CLI entry point, argument parsing
├── __main__.py          # Package entry point
├── core/
│   ├── audio.py         # Audio recording (PyAudio/sounddevice + PortAudio)
│   ├── transcribe.py    # Base backend protocol, dataclasses
│   ├── nemo_backend.py  # NVIDIA GPU (experimental)
│   ├── whisper_backend.py # Mac/CPU fallback
│   └── analyzer.py      # Key points + takeaways generation
```

| Backend | Device | Quality | Speed |
|---------|--------|---------|-------|
| NeMo (nemo) | NVIDIA GPU | Very high (4-speaker) | Fast |
| Whisper (whisper) | CPU | Good (small model) | Slow |
| Whisper+MPS (whisper + --mps) | Apple Silicon | High (medium model) | Fast |

**Note:** NeMo backend is experimental and requires model weights download (~2GB+).

