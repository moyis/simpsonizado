from __future__ import annotations

import json
import subprocess

import mlx_whisper

from pipeline.subtitle_parser import SubtitleEntry

SPANISH_LANGUAGES = {"spa", "es", "esp"}
COMMENTARY_KEYWORDS = {"commentary", "comentario", "director"}

MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}


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


def extract_audio(
    input_path: str, audio_track: str, output_path: str
) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-map", audio_track,
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            output_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to extract audio from {input_path}: {result.stderr}"
        )


def load_model(model_size: str) -> str:
    """Returns the HuggingFace repo path for the given model size."""
    if model_size not in MODEL_REPOS:
        raise ValueError(
            f"Unknown model size: {model_size}. "
            f"Choose from: {', '.join(MODEL_REPOS)}"
        )
    return MODEL_REPOS[model_size]


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


def transcribe_audio(
    audio_path: str, model_repo: str
) -> list[SubtitleEntry]:
    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=model_repo,
        language="es",
        word_timestamps=True,
        condition_on_previous_text=True,
        hallucination_silence_threshold=2.0,
        initial_prompt="Los Simpsons. Homero, Marge, Bart, Lisa, Maggie Simpson. Springfield.",
    )

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
