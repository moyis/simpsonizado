from __future__ import annotations

import json
import math
import multiprocessing
import os
import re
import subprocess
import tempfile

from pipeline.subtitle_parser import SubtitleEntry

FRAME_RATE_DIVISOR = 7
FRAME_FILENAME_PATTERN = re.compile(r"^frame_(\d+)\.webp$")
SUBTITLE_MERGE_GAP = 1  # merge frame ranges within 1 frame of each other
WEBP_QUALITY = 25
WEBP_RESIZE_WIDTH = 960
BATCH_GAP_SECONDS = 10  # merge ranges within 10s for fewer ffmpeg calls


def detect_fps(input_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "0",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "csv=p=0",
            input_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"Failed to detect FPS for {input_path}: {result.stderr}"
        )

    fps_str = result.stdout.strip()
    if "/" in fps_str:
        num, den = fps_str.split("/")
        return int(num) / int(den)
    return float(fps_str)


def find_spanish_subtitle_track(input_path: str) -> int | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "0",
            "-select_streams", "s",
            "-show_entries", "stream=index:stream_tags=language,title",
            "-of", "json",
            input_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    spanish_languages = {"spa", "es", "esp"}
    forced_keywords = {"forced", "forzado"}

    for i, stream in enumerate(streams):
        tags = stream.get("tags", {})
        lang = tags.get("language", "").lower()
        title = tags.get("title", "").lower()
        if lang in spanish_languages and not any(k in title for k in forced_keywords):
            return i  # subtitle stream index (for 0:s:N)

    return None


def extract_subtitles(
    input_path: str, sub_track: int, output_dir: str
) -> str:
    output_path = os.path.join(output_dir, "subtitles.srt")

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-map", f"0:s:{sub_track}",
            "-f", "srt",
            output_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to extract subtitles from {input_path}: {result.stderr}"
        )

    return output_path


def compute_extraction_fps(native_fps: float) -> float:
    return native_fps / FRAME_RATE_DIVISOR


def extract_frames_and_thumbnails(
    input_path: str, output_dir: str, fps: float
) -> None:
    os.makedirs(output_dir, exist_ok=True)

    extraction_fps = compute_extraction_fps(fps)
    frame_pattern = os.path.join(output_dir, "frame_%06d.webp")

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-vf", f"fps={extraction_fps}",
            "-c:v", "libwebp", "-quality", "80",
            frame_pattern,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to extract frames from {input_path}: {result.stderr}"
        )


def remove_unsubtitled_frames(
    frames_dir: str,
    entries: list[SubtitleEntry],
    extraction_fps: float,
) -> int:
    subtitled_frames: set[int] = set()
    for entry in entries:
        start_frame = math.floor((entry.start_ms / 1000) * extraction_fps) + 1
        end_frame = math.floor((entry.end_ms / 1000) * extraction_fps) + 1
        subtitled_frames.update(range(start_frame, end_frame + 1))

    removed = 0
    for filename in os.listdir(frames_dir):
        match = FRAME_FILENAME_PATTERN.match(filename)
        if not match:
            continue
        frame_num = int(match.group(1))
        if frame_num not in subtitled_frames:
            os.remove(os.path.join(frames_dir, filename))
            removed += 1

    return removed


def _merge_ranges(
    ranges: list[tuple[int, int]], gap: int = 0
) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent integer ranges.

    Ranges within ``gap`` of each other are merged.
    """
    if not ranges:
        return []
    sorted_ranges = sorted(ranges)
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        if start <= merged[-1][1] + 1 + gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _compute_subtitle_frame_ranges(
    entries: list[SubtitleEntry],
    extraction_fps: float,
) -> list[tuple[int, int]]:
    """Compute merged 0-based frame number ranges covered by subtitles.

    Uses the same floor-based calculation as ``remove_unsubtitled_frames``
    so both code paths select identical frame sets.
    """
    ranges: list[tuple[int, int]] = []
    for entry in entries:
        n_start = math.floor((entry.start_ms / 1000) * extraction_fps)
        n_end = math.floor((entry.end_ms / 1000) * extraction_fps)
        ranges.append((n_start, n_end))
    return _merge_ranges(ranges, gap=SUBTITLE_MERGE_GAP)


def _convert_jpeg_to_webp(args: tuple[str, str, int]) -> None:
    """Convert a single JPEG file to WebP using cwebp."""
    src, dst, quality = args
    subprocess.run(
        ["cwebp", "-q", str(quality), "-resize", str(WEBP_RESIZE_WIDTH), "0", src, "-o", dst],
        capture_output=True,
    )


def extract_frames_for_subtitles(
    input_path: str,
    output_dir: str,
    fps: float,
    entries: list[SubtitleEntry],
) -> int:
    """Extract frames only during subtitle time windows.

    Two-step pipeline for speed:
    1. ffmpeg seeks to each subtitle batch and extracts as JPEG
    2. cwebp converts subtitle-covered frames to WebP in parallel

    Returns the number of frames extracted.
    """
    os.makedirs(output_dir, exist_ok=True)
    extraction_fps = compute_extraction_fps(fps)

    if not entries:
        return 0

    frame_ranges = _compute_subtitle_frame_ranges(entries, extraction_fps)
    if not frame_ranges:
        return 0

    # Set of 1-based frame numbers covered by subtitles
    subtitle_frames: set[int] = set()
    for start, end in frame_ranges:
        subtitle_frames.update(range(start + 1, end + 2))

    # Merge ranges aggressively for fewer ffmpeg calls
    batch_gap = int(BATCH_GAP_SECONDS * extraction_fps)
    batched_ranges = _merge_ranges(frame_ranges, gap=batch_gap)

    with tempfile.TemporaryDirectory() as tmp_dir:
        jpeg_pattern = os.path.join(tmp_dir, "frame_%06d.jpg")

        # Step 1: Extract as JPEG per batch
        for batch_start, batch_end in batched_ranges:
            start_sec = batch_start / extraction_fps
            duration = (batch_end - batch_start + 1) / extraction_fps
            start_frame = batch_start + 1  # 1-based

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", f"{start_sec:.3f}",
                    "-i", input_path,
                    "-t", f"{duration:.3f}",
                    "-map", "0:v:0",
                    "-vf", f"fps={extraction_fps}",
                    "-start_number", str(start_frame),
                    "-pix_fmt", "yuvj420p",
                    "-q:v", "2",
                    jpeg_pattern,
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Failed to extract frames from {input_path}: "
                    f"{result.stderr}"
                )

        # Step 2: Convert only subtitle-covered JPEGs → WebP
        convert_args: list[tuple[str, str, int]] = []
        for filename in sorted(os.listdir(tmp_dir)):
            if not filename.endswith(".jpg"):
                continue
            frame_num = int(
                filename.replace("frame_", "").replace(".jpg", "")
            )
            if frame_num in subtitle_frames:
                src = os.path.join(tmp_dir, filename)
                dst = os.path.join(
                    output_dir, f"frame_{frame_num:06d}.webp"
                )
                convert_args.append((src, dst, WEBP_QUALITY))

        workers = multiprocessing.cpu_count()
        with multiprocessing.Pool(workers) as pool:
            pool.map(_convert_jpeg_to_webp, convert_args)

    return len(
        [f for f in os.listdir(output_dir) if FRAME_FILENAME_PATTERN.match(f)]
    )
