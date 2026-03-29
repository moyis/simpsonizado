#!/usr/bin/env python3
"""Transcribe Spanish audio files to cleaned SRT subtitles using Whisper.

Usage:
    python scripts/transcribe_subs.py audio/ --subs-dir data/subs --model medium
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import sys
import threading
import time
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Subtitle data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubtitleEntry:
    start_ms: int
    end_ms: int
    text: str


# ---------------------------------------------------------------------------
# SRT cleaner
# ---------------------------------------------------------------------------

MUSIC_AND_SOUND_MARKERS = {"♪", "[Música]", "[Music]", "[Aplausos]", "[Risas]"}

HALLUCINATION_PATTERNS = [
    "gracias por ver",
    "subtítulos por",
    "subtitulos por",
    "suscríbete",
    "gracias por su atención",
    "gracias por su atencion",
]

NAME_CORRECTIONS = {
    # Homero
    "Mo": "Moe",
    "Mero": "Homero",
    "Humbero": "Homero",
    "Homer": "Homero",
    "Omero": "Homero",
    # Marge
    "March": "Marge",
    "Marsh": "Marge",
    "Mark Simpson": "Marge Simpson",
    # Bart
    "Bard": "Bart",
    "Bort": "Bart",
    "Var": "Bart",
    # Lisa
    "Liza": "Lisa",
    # Maggie
    "Magui": "Maggie",
    "Magi": "Maggie",
    "Magda": "Maggie",
    "Smaggy": "Maggie",
    # Burns
    "Burn": "Burns",
    "Berns": "Burns",
    # Smithers
    "Smither": "Smithers",
    "Smythers": "Smithers",
    "Esmider": "Smithers",
    # Moe
    "Mow": "Moe",
    # Barney
    "Barny": "Barney",
    "Barney Gomez": "Barney Gómez",
    "Barney Gombo": "Barney Gómez",
    # Ned
    "Net": "Ned",
    # Krusty
    "Crusty": "Krusty",
    "Crosti": "Krusty",
    "Crosty": "Krusty",
    "Krusti": "Krusty",
    "Krosti": "Krusty",
    "Rosti": "Krusty",
    # Patty
    "Patti": "Patty",
    # Otto
    "Oto": "Otto",
    # Carl
    "Karl": "Carl",
    # Milhouse
    "Millhouse": "Milhouse",
    # Krabappel
    "Cravapal": "Krabappel",
    "Cravapel": "Krabappel",
    "Cravaple": "Krabappel",
    "Crabapel": "Krabappel",
    "Kravapel": "Krabappel",
    "Stricter": "Krabappel",
    "Strickter": "Krabappel",
    # Gorgory (Wiggum)
    "Gorgori": "Gorgory",
    "Gorgor": "Gorgory",
    "Gorgorin": "Gorgory",
    "Gorgoriu": "Gorgory",
    # Ralph
    "Rafa Gorgory": "Ralph Gorgory",
    "Rafa Gorgori": "Ralph Gorgory",
    "Rafa Górgori": "Ralph Gorgory",
    # Seymour (Skinner)
    "Simur": "Seymour",
    "Simul": "Seymour",
    # Kent Brockman
    "Ken Brockman": "Kent Brockman",
    # Hibbert
    "Heber": "Hibbert",
    "Heavers": "Hibbert",
    # Rod y Todd
    "Roddy Todd": "Rod y Todd",
    # Nelson
    "Rupino": "Rufino",
    # Bob Patiño
    "Pop Patiño": "Bob Patiño",
    # McBain
    "McVein": "McBain",
    # Tomy y Daly (Itchy & Scratchy)
    "Tommy y Nally": "Tomy y Daly",
    "Tommy y Dalien": "Tomy y Daly",
    "Tommy y Daddy": "Tomy y Daly",
    # Encías Sangrantes
    "encias sangrantes": "Encías Sangrantes",
    "en cías sangrantes": "Encías Sangrantes",
}

MAX_MERGED_LENGTH = 84


def _reduce_repetitions(match: re.Match) -> str:
    return ", ".join(match.group(0).split()[:3])


def _clean_segment(text: str) -> str:
    text = text.strip()
    text = re.sub(
        r"\b(\w+)(?:\s+\1){2,}\b",
        _reduce_repetitions,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"(?<!\.)\.{2}(?!\.)", "...", text)
    for wrong, correct in NAME_CORRECTIONS.items():
        text = re.sub(rf"\b{wrong}\b", correct, text)
    return text


def _find_repeated_runs(segments: list[SubtitleEntry]) -> set[int]:
    to_remove: set[int] = set()
    i = 0
    while i < len(segments):
        j = i + 1
        text = segments[i].text.strip()
        while j < len(segments) and segments[j].text.strip() == text:
            j += 1
        if j - i >= 3:
            to_remove.update(range(i, j))
        i = j
    return to_remove


def _remove_junk_segments(segments: list[SubtitleEntry]) -> list[SubtitleEntry]:
    repeated = _find_repeated_runs(segments)
    result = []
    for i, entry in enumerate(segments):
        if i in repeated:
            continue
        if entry.text.strip() in MUSIC_AND_SOUND_MARKERS:
            continue
        if len(entry.text.strip()) <= 1:
            continue
        if (entry.end_ms - entry.start_ms) < 100:
            continue
        if any(p in entry.text.strip().lower() for p in HALLUCINATION_PATTERNS):
            continue
        result.append(entry)
    return result


def _merge_short_segments(
    segments: list[SubtitleEntry], min_duration_ms: int = 1000
) -> list[SubtitleEntry]:
    if not segments:
        return []
    result: list[SubtitleEntry] = [segments[0]]
    for entry in segments[1:]:
        if (entry.end_ms - entry.start_ms) >= min_duration_ms:
            result.append(entry)
            continue
        prev = result[-1]
        gap = entry.start_ms - prev.end_ms
        combined = f"{prev.text} {entry.text}"
        if gap < 500 and len(combined) <= MAX_MERGED_LENGTH:
            result[-1] = SubtitleEntry(prev.start_ms, entry.end_ms, combined)
        else:
            result.append(entry)
    return result


def clean_srt(segments: list[SubtitleEntry]) -> list[SubtitleEntry]:
    segments = _remove_junk_segments(segments)
    segments = [
        SubtitleEntry(e.start_ms, e.end_ms, _clean_segment(e.text))
        for e in segments
    ]
    segments = _merge_short_segments(segments)
    return [e for e in segments if e.text]


# ---------------------------------------------------------------------------
# Whisper integration
# ---------------------------------------------------------------------------

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

WHISPER_PROMPT = (
    "Los Simpsons. Homero, Marge, Bart, Lisa, Maggie Simpson. "
    "Moe, Barney, Lenny, Carl. Burns, Smithers, Ned Flanders, "
    "Krusty, Otto, Patty, Selma, Milhouse, Nelson, "
    "Encías Sangrantes Murphy. Springfield."
)

SILENCE_GAP_MS = 400


def _use_mlx() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def load_model(model_size: str) -> object:
    if _use_mlx():
        if model_size not in MLX_MODEL_REPOS:
            raise ValueError(f"Unknown model: {model_size}")
        return MLX_MODEL_REPOS[model_size]
    import whisper
    if model_size not in OPENAI_MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_size}")
    return whisper.load_model(OPENAI_MODEL_NAMES[model_size])


def _split_segment_by_silence(segment: dict) -> list[SubtitleEntry]:
    words = segment.get("words", [])
    if not words:
        text = segment["text"].strip()
        if not text:
            return []
        return [SubtitleEntry(int(segment["start"] * 1000), int(segment["end"] * 1000), text)]

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


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


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
        whisper_opts = dict(
            language="es",
            word_timestamps=True,
            condition_on_previous_text=True,
            hallucination_silence_threshold=2.0,
            initial_prompt=WHISPER_PROMPT,
        )
        if _use_mlx():
            import mlx_whisper
            result = mlx_whisper.transcribe(
                audio_path, path_or_hf_repo=model, **whisper_opts
            )
        else:
            result = model.transcribe(audio_path, **whisper_opts)
    finally:
        stop_event.set()
        timer.join()

    entries: list[SubtitleEntry] = []
    for segment in result["segments"]:
        entries.extend(_split_segment_by_silence(segment))
    return entries


# ---------------------------------------------------------------------------
# SRT writing
# ---------------------------------------------------------------------------

def _ms_to_srt_timestamp(ms: int) -> str:
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    millis = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def segments_to_srt(segments: list[SubtitleEntry], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{_ms_to_srt_timestamp(seg.start_ms)} --> {_ms_to_srt_timestamp(seg.end_ms)}\n")
            f.write(f"{seg.text}\n\n")


# ---------------------------------------------------------------------------
# Episode ID parsing
# ---------------------------------------------------------------------------

EPISODE_PATTERN = re.compile(r"S(\d{2})E(\d{2})", re.IGNORECASE)
AUDIO_EXTENSIONS = {".flac", ".wav", ".mp3", ".m4a", ".ogg"}


def parse_episode_id(filename: str) -> str | None:
    match = EPISODE_PATTERN.search(filename)
    if match:
        return f"S{int(match.group(1)):02d}E{int(match.group(2)):02d}"
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_audio_files(audio_dir: str) -> list[tuple[str, str]]:
    results = []
    for filename in sorted(os.listdir(audio_dir)):
        if os.path.splitext(filename)[1].lower() not in AUDIO_EXTENSIONS:
            continue
        episode_id = parse_episode_id(filename)
        if not episode_id:
            print(f"  Skipping {filename}: could not parse episode ID", file=sys.stderr)
            continue
        results.append((os.path.join(audio_dir, filename), episode_id))
    return results


def transcribe_episode(
    audio_path: str,
    episode_id: str,
    model: object,
    subs_dir: str,
    force: bool = False,
) -> bool:
    srt_path = os.path.join(subs_dir, f"{episode_id}.srt")
    if os.path.exists(srt_path) and not force:
        print(f"[{episode_id}] Skipping (SRT already exists)")
        return True

    start = time.time()
    print(f"[{episode_id}] Transcribing {os.path.basename(audio_path)}...")

    try:
        entries = transcribe_audio(audio_path, model)
        raw_count = len(entries)
        entries = clean_srt(entries)
        segments_to_srt(entries, srt_path)

        elapsed = time.time() - start
        m, s = divmod(int(elapsed), 60)
        print(f"[{episode_id}] Done: {raw_count} raw -> {len(entries)} cleaned ({m}m {s}s)")
        return True
    except Exception as e:
        print(f"[{episode_id}] ERROR: {e}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe Spanish audio files to cleaned SRT subtitles"
    )
    parser.add_argument("audio_dir", help="Directory with audio files (e.g. S01E01.flac)")
    parser.add_argument("--subs-dir", default="data/subs", help="Output directory for SRTs (default: data/subs)")
    parser.add_argument("--model", default="medium", choices=list(MLX_MODEL_REPOS), help="Whisper model (default: medium)")
    parser.add_argument("--force", action="store_true", help="Re-transcribe even if SRT exists")

    args = parser.parse_args()
    if not os.path.isdir(args.audio_dir):
        parser.error(f"Audio directory not found: {args.audio_dir}")

    os.makedirs(args.subs_dir, exist_ok=True)

    audio_files = find_audio_files(args.audio_dir)
    if not audio_files:
        print("No audio files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(audio_files)} audio files. Loading Whisper {args.model} model...")
    model = load_model(args.model)

    succeeded = 0
    failed = 0
    for audio_path, episode_id in audio_files:
        if transcribe_episode(audio_path, episode_id, model, args.subs_dir, args.force):
            succeeded += 1
        else:
            failed += 1

    print(f"\nComplete: {succeeded} succeeded, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
