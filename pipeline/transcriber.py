from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import threading
import time

from pipeline.subtitle_parser import SubtitleEntry

SPANISH_LANGUAGES = {"spa", "es", "esp"}
COMMENTARY_KEYWORDS = {"commentary", "comentario", "director"}

MLX_MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}

OPENAI_MODEL_NAMES = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large-v2": "large-v2",
    "large-v3": "large-v3",
}


def _use_mlx() -> bool:
    """Use MLX on Apple Silicon, openai-whisper everywhere else."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def find_spanish_audio_track(input_path: str) -> str | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "0",
            "-select_streams", "a",
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

    for i, stream in enumerate(streams):
        tags = stream.get("tags", {})
        lang = tags.get("language", "").lower()
        title = tags.get("title", "").lower()

        if lang not in SPANISH_LANGUAGES:
            continue

        if any(keyword in title for keyword in COMMENTARY_KEYWORDS):
            continue

        return f"0:a:{i}"

    return None


def _get_duration_seconds(input_path: str) -> float | None:
    result = subprocess.run(
        [
            "ffprobe", "-v", "0",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            input_path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def extract_audio(
    input_path: str, audio_track: str, output_path: str
) -> float | None:
    """Extract audio and return duration in seconds."""
    duration = _get_duration_seconds(input_path)

    proc = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-map", audio_track,
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "flac",
            "-progress", "pipe:1",
            output_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if duration and proc.stdout:
        for line in proc.stdout:
            match = re.match(r"out_time_ms=(\d+)", line.strip())
            if match:
                current = int(match.group(1)) / 1_000_000
                pct = min(current / duration * 100, 100)
                bar = "█" * int(pct // 2.5) + "░" * (40 - int(pct // 2.5))
                sys.stderr.write(
                    f"\r  Audio: {bar} {pct:5.1f}% ({_format_time(current)}/{_format_time(duration)})"
                )
                sys.stderr.flush()
        sys.stderr.write("\n")

    proc.wait()
    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(
            f"Failed to extract audio from {input_path}: {stderr}"
        )

    return duration


def load_model(model_size: str) -> object:
    """Load and return the whisper model (MLX on Apple Silicon, openai-whisper on CUDA)."""
    if _use_mlx():
        if model_size not in MLX_MODEL_REPOS:
            raise ValueError(
                f"Unknown model size: {model_size}. "
                f"Choose from: {', '.join(MLX_MODEL_REPOS)}"
            )
        return MLX_MODEL_REPOS[model_size]

    import whisper
    if model_size not in OPENAI_MODEL_NAMES:
        raise ValueError(
            f"Unknown model size: {model_size}. "
            f"Choose from: {', '.join(OPENAI_MODEL_NAMES)}"
        )
    return whisper.load_model(OPENAI_MODEL_NAMES[model_size])


SILENCE_GAP_MS = 400


def _split_segment_by_silence(segment: dict) -> list[SubtitleEntry]:
    """Split a segment into multiple entries at silence gaps between words."""
    words = segment.get("words", [])
    if not words:
        text = segment["text"].strip()
        if not text:
            return []
        return [
            SubtitleEntry(
                start_ms=int(segment["start"] * 1000),
                end_ms=int(segment["end"] * 1000),
                text=text,
            )
        ]

    entries: list[SubtitleEntry] = []
    chunk_start = int(words[0]["start"] * 1000)
    chunk_end = int(words[0]["end"] * 1000)
    chunk_words = [words[0]["word"]]

    for prev, word in zip(words, words[1:]):
        gap_ms = int(word["start"] * 1000) - int(prev["end"] * 1000)

        if gap_ms >= SILENCE_GAP_MS:
            text = "".join(chunk_words).strip()
            if text:
                entries.append(SubtitleEntry(chunk_start, chunk_end, text))
            chunk_start = int(word["start"] * 1000)
            chunk_words = []

        chunk_end = int(word["end"] * 1000)
        chunk_words.append(word["word"])

    text = "".join(chunk_words).strip()
    if text:
        entries.append(SubtitleEntry(chunk_start, chunk_end, text))

    return entries


def _transcribe_mlx(audio_path: str, model_repo: str) -> dict:
    import mlx_whisper
    return mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=model_repo,
        language="es",
        word_timestamps=True,
        condition_on_previous_text=True,
        hallucination_silence_threshold=2.0,
        initial_prompt="Los Simpsons. Homero, Marge, Bart, Lisa, Maggie Simpson. Moe, Barney, Lenny, Carl. Springfield.",
    )


def _transcribe_openai(audio_path: str, model: object) -> dict:
    return model.transcribe(
        audio_path,
        language="es",
        word_timestamps=True,
        condition_on_previous_text=True,
        hallucination_silence_threshold=2.0,
        initial_prompt="Los Simpsons. Homero, Marge, Bart, Lisa, Maggie Simpson. Moe, Barney, Lenny, Carl. Springfield.",
    )


def transcribe_audio(
    audio_path: str, model: object, duration: float | None = None
) -> list[SubtitleEntry]:
    stop_event = threading.Event()

    def _progress_timer():
        start = time.time()
        while not stop_event.is_set():
            elapsed = time.time() - start
            msg = f"\r  Whisper: {_format_time(elapsed)} elapsed"
            if duration:
                msg += f" (audio: {_format_time(duration)})"
            sys.stderr.write(msg)
            sys.stderr.flush()
            stop_event.wait(1)
        sys.stderr.write("\n")

    timer = threading.Thread(target=_progress_timer, daemon=True)
    timer.start()

    try:
        if _use_mlx():
            result = _transcribe_mlx(audio_path, model)
        else:
            result = _transcribe_openai(audio_path, model)
    finally:
        stop_event.set()
        timer.join()

    entries: list[SubtitleEntry] = []
    for segment in result["segments"]:
        entries.extend(_split_segment_by_silence(segment))

    return entries


def _ms_to_srt_timestamp(ms: int) -> str:
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    millis = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def segments_to_srt(
    segments: list[SubtitleEntry], output_path: str
) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(
                f"{_ms_to_srt_timestamp(segment.start_ms)} --> "
                f"{_ms_to_srt_timestamp(segment.end_ms)}\n"
            )
            f.write(f"{segment.text}\n")
            f.write("\n")
