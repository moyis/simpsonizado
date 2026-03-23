import re

from pipeline.subtitle_parser import SubtitleEntry

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
    "Mo": "Moe",
    "March": "Marge",
}

MAX_MERGED_LENGTH = 84


def _reduce_repetitions(match: re.Match) -> str:
    full = match.group(0)
    words = full.split()
    return ", ".join(words[:3])


def clean_segment(text: str) -> str:
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


def _is_music_or_sound(text: str) -> bool:
    return text.strip() in MUSIC_AND_SOUND_MARKERS


def _is_single_char(text: str) -> bool:
    return len(text.strip()) <= 1


def _is_too_short(entry: SubtitleEntry) -> bool:
    return (entry.end_ms - entry.start_ms) < 100


def _is_hallucination(text: str) -> bool:
    lower = text.strip().lower()
    return any(pattern in lower for pattern in HALLUCINATION_PATTERNS)


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


def remove_junk_segments(
    segments: list[SubtitleEntry],
) -> list[SubtitleEntry]:
    repeated_indices = _find_repeated_runs(segments)

    result = []
    for i, entry in enumerate(segments):
        if i in repeated_indices:
            continue
        if _is_music_or_sound(entry.text):
            continue
        if _is_single_char(entry.text):
            continue
        if _is_too_short(entry):
            continue
        if _is_hallucination(entry.text):
            continue
        result.append(entry)

    return result


def merge_short_segments(
    segments: list[SubtitleEntry],
    min_duration_ms: int = 1000,
) -> list[SubtitleEntry]:
    if not segments:
        return []

    result: list[SubtitleEntry] = [segments[0]]

    for entry in segments[1:]:
        duration = entry.end_ms - entry.start_ms
        if duration >= min_duration_ms:
            result.append(entry)
            continue

        predecessor = result[-1]
        gap = entry.start_ms - predecessor.end_ms
        combined_text = f"{predecessor.text} {entry.text}"

        if gap < 500 and len(combined_text) <= MAX_MERGED_LENGTH:
            merged = SubtitleEntry(
                start_ms=predecessor.start_ms,
                end_ms=entry.end_ms,
                text=combined_text,
            )
            result[-1] = merged
        else:
            result.append(entry)

    return result


def clean_srt(segments: list[SubtitleEntry]) -> list[SubtitleEntry]:
    segments = remove_junk_segments(segments)

    segments = [
        SubtitleEntry(
            start_ms=entry.start_ms,
            end_ms=entry.end_ms,
            text=clean_segment(entry.text),
        )
        for entry in segments
    ]

    segments = merge_short_segments(segments)

    segments = [entry for entry in segments if entry.text]

    return segments
