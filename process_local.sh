#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv/bin/python"
EPISODES_DIR="episodes"
WHISPER_SRT_DIR="data/whisper_srt"
FRAMES_DIR="public/frames"
DB_PATH="data/simpsonizado.db"

mkdir -p "$WHISPER_SRT_DIR" "$FRAMES_DIR" "data/logs"

log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

TOTAL=$(find "$EPISODES_DIR" -maxdepth 1 -name "*.mkv" | wc -l | tr -d ' ')
PROCESSED=0
SKIPPED=0
FAILED=0
START=$(date +%s)

echo "=========================================="
echo "  Simpsonizado Pipeline (local)"
echo "  Started: $(date)"
echo "  Episodes in folder: $TOTAL"
echo "=========================================="
echo ""

for MKV in "$EPISODES_DIR"/*.mkv; do
    [ -f "$MKV" ] || continue
    EP_ID=$(basename "$MKV" .mkv | grep -oE 'S[0-9]{2}E[0-9]{2}')
    [ -z "$EP_ID" ] && continue

    if [ -f "$WHISPER_SRT_DIR/${EP_ID}.srt" ] && [ -f "$FRAMES_DIR/${EP_ID}/.done" ]; then
        SKIPPED=$((SKIPPED + 1))
        log "[$EP_ID] Already done, skipping. ($((SKIPPED + PROCESSED))/$TOTAL)"
        continue
    fi

    # Step 1: Transcribe
    if [ ! -f "$WHISPER_SRT_DIR/${EP_ID}.srt" ]; then
        log "[$EP_ID] Transcribing... ($((SKIPPED + PROCESSED + 1))/$TOTAL)"
        EP_START=$(date +%s)
        if $VENV -m pipeline.transcribe --input "$MKV" --output-dir "$WHISPER_SRT_DIR" --model medium 2>&1; then
            log "[$EP_ID] Transcribed in $(($(date +%s) - EP_START))s"
        else
            log "[$EP_ID] FAILED transcription"
            FAILED=$((FAILED + 1))
            continue
        fi
    fi

    # Step 2: Extract frames + DB
    if [ ! -f "$FRAMES_DIR/${EP_ID}/.done" ]; then
        log "[$EP_ID] Extracting frames... ($((SKIPPED + PROCESSED + 1))/$TOTAL)"
        EP_START=$(date +%s)
        if $VENV -m pipeline.extract \
            --input "$MKV" \
            --frames-dir "$FRAMES_DIR" \
            --db-path "$DB_PATH" \
            --whisper-srt-dir "$WHISPER_SRT_DIR" 2>&1; then
            log "[$EP_ID] Frames done in $(($(date +%s) - EP_START))s"
        else
            log "[$EP_ID] FAILED extraction"
            FAILED=$((FAILED + 1))
            continue
        fi
    fi

    PROCESSED=$((PROCESSED + 1))
    ELAPSED=$(( ($(date +%s) - START) / 60 ))
    log "[$EP_ID] Complete — Progress: $((SKIPPED + PROCESSED))/$TOTAL (${ELAPSED}m elapsed)"
done

TOTAL_MIN=$(( ($(date +%s) - START) / 60 ))

echo ""
echo "=========================================="
echo "  Pipeline Complete"
echo "  Finished: $(date)"
echo "  Total time: ${TOTAL_MIN} minutes"
echo "  Processed: $PROCESSED"
echo "  Skipped: $SKIPPED"
echo "  Failed: $FAILED"
echo "=========================================="

$VENV -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
count = conn.execute('SELECT COUNT(*) FROM episodes').fetchone()[0]
subs = conn.execute('SELECT COUNT(*) FROM subtitles').fetchone()[0]
print(f'  Episodes in DB: {count}')
print(f'  Subtitles in DB: {subs:,}')
conn.close()
"

echo "  Database: $DB_PATH"
echo "  Frames: $FRAMES_DIR"
echo "=========================================="
