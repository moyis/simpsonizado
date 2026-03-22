from __future__ import annotations

import argparse
import logging
import os

from pipeline.db import Database
from pipeline.extract import parse_episode_id
from pipeline.frame_extractor import compute_extraction_fps, detect_fps
from pipeline.srt_cleaner import clean_srt
from pipeline.subtitle_parser import parse_srt

logger = logging.getLogger(__name__)


def count_frames(frames_dir: str, episode_id: str) -> int:
    episode_dir = os.path.join(frames_dir, episode_id)
    if not os.path.isdir(episode_dir):
        return 0
    return sum(
        1 for f in os.listdir(episode_dir)
        if f.startswith("frame_") and f.endswith(".webp")
    )


def process_episode(
    input_path: str,
    episode_id: str,
    db: Database,
    srt_dir: str,
    frames_dir: str,
    title: str | None = None,
) -> bool:
    srt_path = os.path.join(srt_dir, f"{episode_id}.srt")
    if not os.path.exists(srt_path):
        logger.error("[%s] SRT not found: %s", episode_id, srt_path)
        return False

    try:
        fps = detect_fps(input_path)
        extraction_fps = compute_extraction_fps(fps)

        entries = parse_srt(srt_path)
        entries = clean_srt(entries)

        total_frames = count_frames(frames_dir, episode_id)

        season = int(episode_id[1:3])
        episode = int(episode_id[4:6])

        db.upsert_episode(
            episode_id, title, season, episode,
            extraction_fps, total_frames, "whisper",
        )

        filtered_entries = [
            e for e in entries
            if total_frames == 0
            or (int((e.start_ms / 1000) * extraction_fps) + 1) <= total_frames
        ]
        db.insert_subtitles(episode_id, filtered_entries, extraction_fps)

        logger.info(
            "[%s] Inserted %d subtitles (fps=%.2f, frames=%d)",
            episode_id, len(filtered_entries), extraction_fps, total_frames,
        )
        return True

    except Exception:
        logger.exception("[%s] Failed to build database entry.", episode_id)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build SQLite database from Whisper SRTs and extracted frames"
    )
    parser.add_argument("--input", help="Path to a single .mkv file")
    parser.add_argument("--input-dir", help="Path to directory of .mkv files")
    parser.add_argument(
        "--srt-dir",
        default="data/whisper_srt",
        help="Directory with SRT files (default: data/whisper_srt)",
    )
    parser.add_argument(
        "--frames-dir",
        default="public/frames",
        help="Directory with extracted frames (default: public/frames)",
    )
    parser.add_argument(
        "--db-path",
        default="data/simpsonizado.db",
        help="Path to SQLite database (default: data/simpsonizado.db)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.input and not args.input_dir:
        parser.error("Either --input or --input-dir is required")

    if args.input and args.input_dir:
        parser.error("Cannot use both --input and --input-dir")

    os.makedirs(os.path.dirname(args.db_path) or ".", exist_ok=True)

    db = Database(args.db_path)

    if args.input:
        episode_id = parse_episode_id(os.path.basename(args.input))
        if not episode_id:
            parser.error("Could not parse episode ID from filename.")
        process_episode(
            args.input, episode_id, db, args.srt_dir, args.frames_dir,
        )
    else:
        mkv_files = sorted(
            f for f in os.listdir(args.input_dir) if f.endswith(".mkv")
        )

        succeeded = 0
        failed = 0

        for filename in mkv_files:
            episode_id = parse_episode_id(filename)
            if not episode_id:
                logger.warning("Skipping %s: could not parse episode ID", filename)
                continue
            input_path = os.path.join(args.input_dir, filename)
            if process_episode(
                input_path, episode_id, db, args.srt_dir, args.frames_dir,
            ):
                succeeded += 1
            else:
                failed += 1

        logger.info("Batch complete: %d succeeded, %d failed", succeeded, failed)

    db.close()


if __name__ == "__main__":
    main()
