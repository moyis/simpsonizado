#!/usr/bin/env python3
"""Remove frames not covered by any subtitle range.

Keeps only frames where timestamp falls within some subtitle's [start_ms, end_ms].

Usage:
    python scripts/prune_frames.py data/simpsonizado.db frontend/public/frames --dry-run
    python scripts/prune_frames.py data/simpsonizado.db frontend/public/frames
"""

import argparse
import os
import re
import sqlite3
import sys

FRAME_PATTERN = re.compile(r"frame_(\d{8})\.\w+$")
FPS = 12


def get_subtitle_ranges(db_path: str) -> dict[str, list[tuple[int, int]]]:
    conn = sqlite3.connect(db_path, timeout=30)
    rows = conn.execute(
        "SELECT episode_id, start_ms, end_ms FROM subtitles ORDER BY episode_id, start_ms"
    ).fetchall()
    conn.close()

    ranges: dict[str, list[tuple[int, int]]] = {}
    for episode_id, start_ms, end_ms in rows:
        ranges.setdefault(episode_id, []).append((start_ms, end_ms))
    return ranges


def snap_to_frame_ms(ms: int) -> int:
    frame_index = round(ms * FPS / 1000)
    return frame_index * 1000 // FPS


def frame_covered(frame_ms: int, subtitle_ranges: list[tuple[int, int]]) -> bool:
    for start_ms, end_ms in subtitle_ranges:
        start_snapped = snap_to_frame_ms(start_ms)
        end_snapped = snap_to_frame_ms(end_ms)
        if start_snapped <= frame_ms <= end_snapped:
            return True
        if frame_ms < start_snapped:
            break
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove frames not assigned to any subtitle")
    parser.add_argument("db_path", help="SQLite database path")
    parser.add_argument("frames_dir", help="Frames directory (e.g. frontend/public/frames)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    if not os.path.isfile(args.db_path):
        print(f"Database not found: {args.db_path}", file=sys.stderr)
        sys.exit(1)

    ranges = get_subtitle_ranges(args.db_path)
    print(f"Loaded subtitle ranges for {len(ranges)} episodes")

    total_removed = 0
    total_kept = 0
    total_bytes = 0

    for episode_dir in sorted(os.listdir(args.frames_dir)):
        ep_path = os.path.join(args.frames_dir, episode_dir)
        if not os.path.isdir(ep_path):
            continue

        subtitle_ranges = ranges.get(episode_dir, [])
        if not subtitle_ranges:
            print(f"[{episode_dir}] No subtitles in DB — skipping")
            continue

        removed = 0
        kept = 0
        ep_bytes = 0

        for filename in os.listdir(ep_path):
            match = FRAME_PATTERN.match(filename)
            if not match:
                continue

            frame_ms = int(match.group(1))
            filepath = os.path.join(ep_path, filename)

            if frame_covered(frame_ms, subtitle_ranges):
                kept += 1
            else:
                size = os.path.getsize(filepath)
                ep_bytes += size
                removed += 1
                if not args.dry_run:
                    os.remove(filepath)

        total_removed += removed
        total_kept += kept
        total_bytes += ep_bytes
        print(f"[{episode_dir}] kept {kept}, {'would remove' if args.dry_run else 'removed'} {removed} ({ep_bytes / 1024 / 1024:.1f} MB)")

    action = "Would remove" if args.dry_run else "Removed"
    print(f"\n{action} {total_removed} frames ({total_bytes / 1024 / 1024 / 1024:.2f} GB), kept {total_kept}")


if __name__ == "__main__":
    main()
