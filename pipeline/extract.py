from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from pipeline import frame_extractor
from pipeline.db import Database
from pipeline.frame_extractor import compute_extraction_fps
from pipeline.subtitle_parser import parse_srt

EPISODE_PATTERN = re.compile(r"S(\d{2})E(\d{2})", re.IGNORECASE)


def parse_episode_id(filename: str) -> str | None:
    match = EPISODE_PATTERN.search(filename)
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        return f"S{season:02d}E{episode:02d}"
    return None


def is_episode_done(frames_dir: str, episode_id: str) -> bool:
    marker = os.path.join(frames_dir, episode_id, ".done")
    return os.path.exists(marker)


def mark_episode_done(frames_dir: str, episode_id: str) -> None:
    marker = os.path.join(frames_dir, episode_id, ".done")
    with open(marker, "w") as f:
        f.write("")


def _log(episode_id: str, message: str) -> None:
    print(f"[{episode_id}] {message}", flush=True)


def _log_error(episode_id: str, message: str) -> None:
    print(f"[{episode_id}] ERROR: {message}", file=sys.stderr, flush=True)


def process_episode(
    input_path: str,
    episode_id: str,
    frames_dir: str,
    db_path: str,
    sub_track: int | None = None,
    title: str | None = None,
    whisper_srt_dir: str | None = None,
    no_whisper: bool = False,
) -> bool:
    start_time = time.time()
    episode_frames_dir = os.path.join(frames_dir, episode_id)

    # Resumability: skip if already done
    if is_episode_done(frames_dir, episode_id):
        _log(episode_id, "Already processed, skipping.")
        return True

    # Clean up partial extraction
    if os.path.exists(episode_frames_dir):
        _log(episode_id, "Partial extraction found, cleaning up...")
        shutil.rmtree(episode_frames_dir)

    try:
        # Step 1: Detect FPS
        _log(episode_id, "Detecting FPS...")
        fps = frame_extractor.detect_fps(input_path)
        _log(episode_id, f"FPS: {fps:.3f}")

        # Step 2: Load subtitles (Whisper SRT preferred)
        subtitle_source = "embedded"
        whisper_srt_path = None
        if whisper_srt_dir and not no_whisper:
            candidate = os.path.join(whisper_srt_dir, f"{episode_id}.srt")
            if os.path.exists(candidate):
                whisper_srt_path = candidate

        if whisper_srt_path:
            _log(episode_id, "Using Whisper SRT.")
            entries = parse_srt(whisper_srt_path)
            subtitle_source = "whisper"
        else:
            # Fall back to embedded subtitles
            if sub_track is None:
                _log(episode_id, "Finding Spanish subtitle track...")
                sub_track = frame_extractor.find_spanish_subtitle_track(input_path)
                if sub_track is None:
                    _log_error(episode_id, "No Spanish subtitle track found.")
                    return False

            with tempfile.TemporaryDirectory() as tmp_dir:
                _log(episode_id, "Extracting subtitles...")
                srt_path = frame_extractor.extract_subtitles(
                    input_path, sub_track, tmp_dir
                )
                entries = parse_srt(srt_path)

        _log(episode_id, f"{len(entries)} subtitle entries found.")

        # Step 4: Extract frames (subtitle windows only)
        _log(episode_id, "Extracting frames...")
        frame_count = frame_extractor.extract_frames_for_subtitles(
            input_path, episode_frames_dir, fps, entries
        )
        _log(episode_id, f"{frame_count:,} frames extracted.")

        # Step 5: Insert into database
        _log(episode_id, "Inserting into database...")
        season_match = EPISODE_PATTERN.search(episode_id)
        season = int(season_match.group(1))
        episode = int(season_match.group(2))

        extraction_fps = compute_extraction_fps(fps)

        db = Database(db_path)
        db.upsert_episode(episode_id, title, season, episode, extraction_fps, frame_count, subtitle_source)

        # Filter out entries beyond video duration
        total_frames = frame_count
        filtered_entries = [
            e for e in entries
            if (int((e.start_ms / 1000) * extraction_fps) + 1) <= total_frames
        ]
        db.insert_subtitles(episode_id, filtered_entries, extraction_fps)
        db.close()

        # Mark done
        mark_episode_done(frames_dir, episode_id)

        elapsed = time.time() - start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        _log(episode_id, f"Complete ({minutes}m {seconds}s)")
        return True

    except Exception as e:
        _log_error(episode_id, str(e))
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Extract subtitles and frames from Simpsons episodes"
    )
    parser.add_argument("--input", help="Path to a single .mkv file")
    parser.add_argument("--input-dir", help="Path to directory of .mkv files")
    parser.add_argument("--episode", help="Episode ID (e.g. S01E01)")
    parser.add_argument("--title", help="Episode title (single mode only)")
    parser.add_argument(
        "--sub-track", type=int, help="Subtitle track index (0-based)"
    )
    parser.add_argument(
        "--frames-dir",
        default="public/frames",
        help="Output directory for frames (default: public/frames)",
    )
    parser.add_argument(
        "--db-path",
        default="data/simpsonizado.db",
        help="Path to SQLite database (default: data/simpsonizado.db)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers for batch mode (default: 1)",
    )
    parser.add_argument(
        "--whisper-srt-dir",
        default="data/whisper_srt",
        help="Directory with Whisper-generated SRT files (default: data/whisper_srt)",
    )
    parser.add_argument(
        "--no-whisper",
        action="store_true",
        help="Ignore Whisper SRTs, always use embedded subtitles",
    )

    args = parser.parse_args()

    if not args.input and not args.input_dir:
        parser.error("Either --input or --input-dir is required")

    if args.input and args.input_dir:
        parser.error("Cannot use both --input and --input-dir")

    if args.title and args.input_dir:
        parser.error("--title is only valid with --input, not --input-dir")

    # Ensure output dirs exist
    os.makedirs(args.frames_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.db_path) or ".", exist_ok=True)

    if args.input:
        episode_id = args.episode or parse_episode_id(
            os.path.basename(args.input)
        )
        if not episode_id:
            parser.error(
                "Could not determine episode ID. Use --episode to specify."
            )
        process_episode(
            args.input, episode_id, args.frames_dir, args.db_path,
            args.sub_track, args.title, args.whisper_srt_dir, args.no_whisper,
        )
    else:
        mkv_files = sorted(
            f for f in os.listdir(args.input_dir) if f.endswith(".mkv")
        )
        episodes = []
        for filename in mkv_files:
            episode_id = parse_episode_id(filename)
            if not episode_id:
                print(
                    f"Skipping {filename}: could not parse episode ID",
                    file=sys.stderr,
                )
                continue
            episodes.append((
                os.path.join(args.input_dir, filename),
                episode_id,
            ))

        succeeded = 0
        failed = 0
        workers = min(args.workers, len(episodes)) if episodes else 1

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_episode,
                    input_path, episode_id,
                    args.frames_dir, args.db_path,
                    args.sub_track,
                    None,  # title
                    args.whisper_srt_dir,
                    args.no_whisper,
                ): episode_id
                for input_path, episode_id in episodes
            }
            for future in as_completed(futures):
                if future.result():
                    succeeded += 1
                else:
                    failed += 1

        print(f"\nBatch complete: {succeeded} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
