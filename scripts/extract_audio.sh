#!/bin/bash
set -euo pipefail

EPISODES_DIR="${1:?Usage: $0 <episodes_dir> [output_dir]}"
OUTPUT_DIR="${2:-./audio}"

mkdir -p "$OUTPUT_DIR"

for season_dir in "$EPISODES_DIR"/Temporada\ *; do
    [ -d "$season_dir" ] || continue

    for mkv in "$season_dir"/Los\ Simpson\ -\ S*E*\ -\ vip.hdlatino.us.mkv; do
        [ -f "$mkv" ] || continue

        raw_id=$(basename "$mkv" | grep -oE 'S[0-9]+E[0-9]+')
        [ -z "$raw_id" ] && continue

        ep_id=$(echo "$raw_id" | awk -F'[SEse]' '{printf "S%02dE%02d", $2+0, $3+0}')

        out_file="$OUTPUT_DIR/${ep_id}.flac"
        [ -f "$out_file" ] && { echo "[$ep_id] Skipping (already exists)"; continue; }

        # Find the Spanish Latino audio track index
        track_index=""

        # First try: look for a track with "latino" in the title
        track_index=$(ffprobe -v error -select_streams a \
            -show_entries stream=index:stream_tags=title \
            -of csv=p=0 "$mkv" 2>/dev/null \
            | grep -i 'latino' \
            | head -1 \
            | cut -d',' -f1) || true

        # Second try: look for a track with "espa" in the title (Español)
        if [ -z "$track_index" ]; then
            track_index=$(ffprobe -v error -select_streams a \
                -show_entries stream=index:stream_tags=title \
                -of csv=p=0 "$mkv" 2>/dev/null \
                | grep -i 'espa' \
                | head -1 \
                | cut -d',' -f1) || true
        fi

        # Third try: look for a track with language=spa
        if [ -z "$track_index" ]; then
            track_index=$(ffprobe -v error -select_streams a \
                -show_entries stream=index:stream_tags=language \
                -of csv=p=0 "$mkv" 2>/dev/null \
                | grep -i 'spa' \
                | head -1 \
                | cut -d',' -f1) || true
        fi

        if [ -z "$track_index" ]; then
            echo "[$ep_id] WARNING: No Spanish audio track found, skipping"
            echo "  Available tracks:"
            ffprobe -v error -select_streams a \
                -show_entries stream=index:stream_tags=language,title \
                -of csv=p=0 "$mkv" 2>/dev/null | sed 's/^/    /'
            continue
        fi

        echo "[$ep_id] Extracting Spanish Latino audio (stream $track_index)..."
        ffmpeg -i "$mkv" -map "0:${track_index}" -c:a flac "$out_file" \
            -loglevel warning -stats
        echo "[$ep_id] Done"
    done
done

echo "All episodes processed."
