#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv/bin/python"
NAS_BASE="/Volumes/The Simpsons"
EPISODES_DIR="episodes"
WHISPER_SRT_DIR="data/whisper_srt"
FRAMES_DIR="public/frames"
DB_PATH="data/simpsonizado.db"
BATCH_SIZE=3  # seasons per batch

mkdir -p "$WHISPER_SRT_DIR" "$FRAMES_DIR" "data/logs" "$EPISODES_DIR"

log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

# Count total episodes across all seasons
TOTAL_EPISODES=0
for SEASON in $(seq 1 12); do
    SEASON_DIR=$(printf "%s/Temporada %02d" "$NAS_BASE" "$SEASON")
    [ -d "$SEASON_DIR" ] || continue
    COUNT=$(find "$SEASON_DIR" -maxdepth 1 -name "*.mkv" -not -name "*.tmp" 2>/dev/null | wc -l | tr -d ' ')
    TOTAL_EPISODES=$((TOTAL_EPISODES + COUNT))
done

PROCESSED=0
ALREADY_DONE=0
FAILED=0
PIPELINE_START=$(date +%s)

echo "=========================================="
echo "  Simpsonizado Pipeline"
echo "  Started: $(date)"
echo "  Total episodes on NAS: $TOTAL_EPISODES"
echo "  Batch size: $BATCH_SIZE seasons"
echo "=========================================="
echo ""

# Backup database once
if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "${DB_PATH}.bak.$(date +%Y%m%d_%H%M%S)"
    log "Database backed up."
fi

# Process seasons in batches
for BATCH_START in $(seq 1 $BATCH_SIZE 12); do
    BATCH_END=$((BATCH_START + BATCH_SIZE - 1))
    [ "$BATCH_END" -gt 12 ] && BATCH_END=12
    BATCH_LABEL="Seasons $(printf '%02d' $BATCH_START)-$(printf '%02d' $BATCH_END)"

    # Collect all episodes that need processing in this batch
    BATCH_EPISODES=()
    BATCH_SOURCES=()
    BATCH_SKIP=0

    for SEASON in $(seq "$BATCH_START" "$BATCH_END"); do
        SEASON_DIR=$(printf "%s/Temporada %02d" "$NAS_BASE" "$SEASON")
        [ -d "$SEASON_DIR" ] || continue

        for MKV in "$SEASON_DIR"/*.mkv; do
            [ -f "$MKV" ] || continue
            [[ "$MKV" == *.tmp ]] && continue
            EP_ID=$(basename "$MKV" | grep -oE 'S[0-9]{2}E[0-9]{2}')
            [ -z "$EP_ID" ] && continue

            if [ -f "$WHISPER_SRT_DIR/${EP_ID}.srt" ] && [ -f "$FRAMES_DIR/${EP_ID}/.done" ]; then
                BATCH_SKIP=$((BATCH_SKIP + 1))
                ALREADY_DONE=$((ALREADY_DONE + 1))
            else
                BATCH_EPISODES+=("$EP_ID")
                BATCH_SOURCES+=("$MKV")
            fi
        done
    done

    if [ ${#BATCH_EPISODES[@]} -eq 0 ]; then
        log "[$BATCH_LABEL] All episodes already processed ($BATCH_SKIP skipped)."
        continue
    fi

    echo ""
    echo "=========================================="
    log "[$BATCH_LABEL] ${#BATCH_EPISODES[@]} to process, $BATCH_SKIP already done"
    echo "=========================================="

    # --- PARALLEL COPY: 4 at a time to avoid choking NAS ---
    MAX_PARALLEL_COPIES=4
    BATCH_START_TIME=$(date +%s)
    log "[$BATCH_LABEL] Copying ${#BATCH_EPISODES[@]} episodes from NAS ($MAX_PARALLEL_COPIES at a time)..."
    COPY_PIDS=()
    DONE_COPIES=0
    TOTAL_TO_COPY=0

    for i in "${!BATCH_EPISODES[@]}"; do
        EP_ID="${BATCH_EPISODES[$i]}"
        SRC="${BATCH_SOURCES[$i]}"
        DEST="$EPISODES_DIR/${EP_ID}.mkv"

        [ -L "$DEST" ] && rm "$DEST"
        if [ ! -f "$DEST" ]; then
            cp "$SRC" "$DEST" &
            COPY_PIDS+=($!)
            TOTAL_TO_COPY=$((TOTAL_TO_COPY + 1))

            # Throttle: wait for one to finish when we hit the limit
            if [ ${#COPY_PIDS[@]} -ge $MAX_PARALLEL_COPIES ]; then
                wait "${COPY_PIDS[0]}"
                COPY_PIDS=("${COPY_PIDS[@]:1}")
                DONE_COPIES=$((DONE_COPIES + 1))
                log "  Copied $DONE_COPIES / ${#BATCH_EPISODES[@]}"
            fi
        fi
    done

    # Wait for remaining copies
    for PID in "${COPY_PIDS[@]}"; do
        wait "$PID"
        DONE_COPIES=$((DONE_COPIES + 1))
        log "  Copied $DONE_COPIES / ${#BATCH_EPISODES[@]}"
    done
    COPY_END=$(date +%s)
    log "[$BATCH_LABEL] All files copied in $((COPY_END - BATCH_START_TIME))s"

    # --- TRANSCRIBE: one by one (GPU bound) ---
    log "[$BATCH_LABEL] Step 1/2: Whisper transcription..."
    EP_NUM=0
    for EP_ID in "${BATCH_EPISODES[@]}"; do
        EP_NUM=$((EP_NUM + 1))
        MKV="$EPISODES_DIR/${EP_ID}.mkv"
        [ -f "$MKV" ] || continue

        if [ -f "$WHISPER_SRT_DIR/${EP_ID}.srt" ]; then
            log "  [$EP_ID] SRT exists, skipping. ($EP_NUM/${#BATCH_EPISODES[@]})"
            continue
        fi

        log "  [$EP_ID] Transcribing... ($EP_NUM/${#BATCH_EPISODES[@]})"
        EP_START=$(date +%s)
        if $VENV -m pipeline.transcribe --input "$MKV" --output-dir "$WHISPER_SRT_DIR" --model medium 2>&1; then
            EP_END=$(date +%s)
            log "  [$EP_ID] Transcribed in $((EP_END - EP_START))s"
        else
            EP_END=$(date +%s)
            log "  [$EP_ID] FAILED transcription after $((EP_END - EP_START))s"
            FAILED=$((FAILED + 1))
        fi
    done

    # --- EXTRACT FRAMES: one by one (heavy I/O) ---
    log "[$BATCH_LABEL] Step 2/2: Frame extraction + database..."
    EP_NUM=0
    for EP_ID in "${BATCH_EPISODES[@]}"; do
        EP_NUM=$((EP_NUM + 1))
        MKV="$EPISODES_DIR/${EP_ID}.mkv"
        [ -f "$MKV" ] || continue

        if [ -f "$FRAMES_DIR/${EP_ID}/.done" ]; then
            log "  [$EP_ID] Frames exist, skipping. ($EP_NUM/${#BATCH_EPISODES[@]})"
            continue
        fi

        if [ ! -f "$WHISPER_SRT_DIR/${EP_ID}.srt" ]; then
            log "  [$EP_ID] No SRT, skipping. ($EP_NUM/${#BATCH_EPISODES[@]})"
            continue
        fi

        log "  [$EP_ID] Extracting frames... ($EP_NUM/${#BATCH_EPISODES[@]})"
        EP_START=$(date +%s)
        if $VENV -m pipeline.extract \
            --input "$MKV" \
            --frames-dir "$FRAMES_DIR" \
            --db-path "$DB_PATH" \
            --whisper-srt-dir "$WHISPER_SRT_DIR" 2>&1; then
            EP_END=$(date +%s)
            PROCESSED=$((PROCESSED + 1))
            DONE_SO_FAR=$((PROCESSED + ALREADY_DONE))
            log "  [$EP_ID] Done in $((EP_END - EP_START))s — Progress: $DONE_SO_FAR / $TOTAL_EPISODES"
        else
            EP_END=$(date +%s)
            log "  [$EP_ID] FAILED extraction after $((EP_END - EP_START))s"
            FAILED=$((FAILED + 1))
        fi
    done

    # Clean up local copies for this batch
    log "[$BATCH_LABEL] Cleaning up local MKV files..."
    for EP_ID in "${BATCH_EPISODES[@]}"; do
        LOCAL="$EPISODES_DIR/${EP_ID}.mkv"
        [ -f "$LOCAL" ] && [ ! -L "$LOCAL" ] && rm "$LOCAL"
    done

    BATCH_END_TIME=$(date +%s)
    BATCH_MIN=$(( (BATCH_END_TIME - BATCH_START_TIME) / 60 ))
    log "[$BATCH_LABEL] Complete in ${BATCH_MIN}m — Total: $((PROCESSED + ALREADY_DONE)) / $TOTAL_EPISODES"
    echo ""
done

# Summary
PIPELINE_END=$(date +%s)
TOTAL_ELAPSED=$(( (PIPELINE_END - PIPELINE_START) / 60 ))

echo ""
echo "=========================================="
echo "  Pipeline Complete"
echo "  Finished: $(date)"
echo "  Total time: ${TOTAL_ELAPSED} minutes"
echo "  Processed: $PROCESSED"
echo "  Already done: $ALREADY_DONE"
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
