#!/bin/bash
set -euo pipefail

EPISODES_DIR="${1:?Usage: $0 <episodes_dir> [frames_dir]}"
FRAMES_DIR="${2:-./frames}"
FPS=12

for season_dir in "$EPISODES_DIR"/Temporada\ *; do
    [ -d "$season_dir" ] || continue

    for mkv in "$season_dir"/Los\ Simpson\ -\ S*E*\ -\ vip.hdlatino.us.mkv; do
        [ -f "$mkv" ] || continue

        raw_id=$(basename "$mkv" | grep -oE 'S[0-9]+E[0-9]+')
        [ -z "$raw_id" ] && continue

        ep_id=$(echo "$raw_id" | awk -F'[SEse]' '{printf "S%02dE%02d", $2+0, $3+0}')

        ep_out="$FRAMES_DIR/$ep_id"
        [ -f "$ep_out/.done" ] && { echo "[$ep_id] Skipping (already done)"; continue; }

        echo "[$ep_id] Extracting frames..."
        rm -rf "$ep_out"
        mkdir -p "$ep_out"

        ffmpeg -i "$mkv" \
            -vf "fps=$FPS,scale=960:-1" \
            -pix_fmt yuvj420p \
            -q:v 4 \
            -threads 0 \
            -start_number 0 \
            "$ep_out/seq_%08d.jpg" \
            -loglevel warning -stats

        echo "[$ep_id] Renaming to timestamps..."
        i=0
        for f in "$ep_out"/seq_*.jpg; do
            ms=$(( i * 1000 / FPS ))
            mv "$f" "$ep_out/$(printf 'frame_%08d.jpg' "$ms")"
            i=$((i + 1))
        done

        touch "$ep_out/.done"
        echo "[$ep_id] Done ($i frames)"
    done
done

echo "All episodes processed."
