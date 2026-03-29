#!/bin/bash
set -euo pipefail

FRAMES_DIR="${1:?Usage: $0 <frames_dir> <output_dir> [workers]}"
OUTPUT_DIR="${2:?Usage: $0 <frames_dir> <output_dir> [workers]}"
WORKERS="${3:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}"
QUALITY=25

convert_frame() {
    local jpg="$1"
    local relative="${jpg#$FRAMES_DIR/}"
    local webp="$OUTPUT_DIR/${relative%.jpg}.webp"
    mkdir -p "$(dirname "$webp")"
    cwebp -q "$QUALITY" -resize 960 0 "$jpg" -o "$webp" -quiet
}
export -f convert_frame
export QUALITY FRAMES_DIR OUTPUT_DIR

total=$(find "$FRAMES_DIR" -name 'frame_*.jpg' | wc -l | tr -d ' ')
echo "Converting $total JPG frames to WebP (quality=$QUALITY, workers=$WORKERS)..."
echo "  Source: $FRAMES_DIR"
echo "  Output: $OUTPUT_DIR"

find "$FRAMES_DIR" -name 'frame_*.jpg' -print0 \
    | xargs -0 -P "$WORKERS" -I {} bash -c 'convert_frame "$@"' _ {}

converted=$(find "$OUTPUT_DIR" -name 'frame_*.webp' | wc -l | tr -d ' ')
echo "Done: $converted/$total converted"
