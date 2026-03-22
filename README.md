# Simpsonizado

Search engine for Simpsons quotes in Spanish. Type a phrase, get the exact frame.

## How it works

```
.mkv episodes
    ↓
pipeline/transcribe.py  →  Whisper transcription (Spanish audio → SRT)
    ↓
pipeline/extract.py     →  Frame extraction + subtitle indexing
    ↓
public/frames/          →  WebP frames (~3.4 fps)
data/simpsonizado.db    →  SQLite with FTS5 full-text search
    ↓
frontend/               →  Astro + Preact web app
```

## Prerequisites

- Python 3.14+ with a virtual environment
- Node.js 22+ (or Bun)
- FFmpeg and cwebp installed
- Simpsons episodes as `.mkv` files

## Setup

```bash
# Python pipeline
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Frontend
cd frontend
bun install
```

## Usage

### 1. Transcribe episodes (optional)

Generate Spanish subtitles from audio using Whisper. Skip this if your `.mkv` files already have embedded Spanish subtitles.

```bash
python -m pipeline.transcribe episodes/S05E05.mkv
```

- Extracts Spanish audio track, transcribes with mlx-whisper
- Outputs SRT files to `data/whisper_srt/`
- Cleans hallucinations, deduplicates, and merges short segments

Options:

```bash
# Specify Whisper model (default: mlx-community/whisper-large-v3-mlx)
python -m pipeline.transcribe episodes/*.mkv --model mlx-community/whisper-medium-mlx

# Process multiple episodes
python -m pipeline.transcribe episodes/S05E*.mkv
```

### 2. Extract frames and index subtitles

```bash
python -m pipeline.extract episodes/S05E05.mkv
```

This will:
1. Detect video FPS via ffprobe
2. Load subtitles (prefers Whisper SRT from `data/whisper_srt/`, falls back to embedded Spanish track)
3. Extract frames as WebP to `public/frames/{episode}/`
4. Index subtitles in SQLite with FTS5 full-text search

The process is resumable — episodes with a `.done` marker are skipped.

Options:

```bash
# Process all episodes
python -m pipeline.extract episodes/*.mkv

# Specify database path
python -m pipeline.extract episodes/*.mkv --db data/simpsonizado.db

# Specify output directory for frames
python -m pipeline.extract episodes/*.mkv --out public/frames
```

### 3. Run the frontend

```bash
cd frontend
bun run dev
```

Open `http://localhost:4321` and search for any quote in Spanish.

### Build for production

```bash
cd frontend
bun run build
node dist/server/entry.mjs
```

The `DATABASE_PATH` environment variable controls where the server looks for the SQLite database (defaults to `../data/simpsonizado.db`).

## Project structure

```
pipeline/
  extract.py           # Frame + subtitle extraction CLI
  transcribe.py        # Whisper transcription CLI
  frame_extractor.py   # FFmpeg frame extraction
  subtitle_parser.py   # SRT parser
  transcriber.py       # Whisper audio processing
  srt_cleaner.py       # Subtitle cleaning & deduplication
  db.py                # SQLite schema and operations

frontend/
  src/
    pages/
      index.astro                      # Home / search page
      api/search.ts                    # Full-text search endpoint
      api/random.ts                    # Random frame endpoint
      frame/[episode]/[frame].astro    # Frame detail page
    components/
      SearchBox.tsx                    # Search results grid
      NavSearch.tsx                    # Nav bar search input + random button
    lib/
      sqlite-search.ts                # SQLite FTS5 search service
      search-factory.ts               # Service singleton factory
      types.ts                        # TypeScript interfaces
      format.ts                       # Formatting utilities

data/
  simpsonizado.db      # SQLite database (gitignored)
  whisper_srt/         # Whisper-generated SRT files (gitignored)

public/frames/         # Extracted WebP frames (gitignored)
```

## Search features

- **FTS5 full-text search** with BM25 relevance ranking
- **Diacritics-insensitive** — searching "tambien" matches "también"
- **Random frame** button for discovery

## Tech stack

- **Pipeline:** Python, FFmpeg, mlx-whisper, SQLite
- **Frontend:** Astro 6, Preact, Tailwind CSS 4, better-sqlite3
- **Search:** SQLite FTS5 with `unicode61 remove_diacritics 2` tokenizer

## Tests

```bash
# Pipeline tests
cd pipeline && pytest

# Frontend tests
cd frontend && bun run test
```
