import re
from dataclasses import dataclass

TIMESTAMP_PATTERN = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


@dataclass(frozen=True)
class SubtitleEntry:
    start_ms: int
    end_ms: int
    text: str


def _timestamp_to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(millis)
    )


def parse_srt(file_path: str) -> list[SubtitleEntry]:
    with open(file_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    entries = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        timestamp_match = None
        timestamp_line_idx = -1

        for i, line in enumerate(lines):
            match = TIMESTAMP_PATTERN.match(line.strip())
            if match:
                timestamp_match = match
                timestamp_line_idx = i
                break

        if timestamp_match is None:
            continue

        text_lines = lines[timestamp_line_idx + 1 :]
        text = " ".join(line.strip() for line in text_lines if line.strip())

        if not text:
            continue

        g = timestamp_match.groups()
        start_ms = _timestamp_to_ms(g[0], g[1], g[2], g[3])
        end_ms = _timestamp_to_ms(g[4], g[5], g[6], g[7])

        entries.append(SubtitleEntry(start_ms=start_ms, end_ms=end_ms, text=text))

    return entries
