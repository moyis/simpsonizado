#!/usr/bin/env python3
"""Build SQLite database from SRT subtitles and verify frame coverage.

Usage:
    python scripts/build_db.py data/subs --frames-dir exports/frames --db-path data/simpsonizado.db
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
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
# SRT parser
# ---------------------------------------------------------------------------

TIMESTAMP_PATTERN = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def _timestamp_to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1_000 + int(millis)


def parse_srt(file_path: str) -> list[SubtitleEntry]:
    with open(file_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    entries = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        ts_match = None
        ts_idx = -1
        for i, line in enumerate(lines):
            match = TIMESTAMP_PATTERN.match(line.strip())
            if match:
                ts_match = match
                ts_idx = i
                break

        if ts_match is None:
            continue

        text = " ".join(l.strip() for l in lines[ts_idx + 1:] if l.strip())
        if not text:
            continue

        g = ts_match.groups()
        entries.append(SubtitleEntry(
            start_ms=_timestamp_to_ms(g[0], g[1], g[2], g[3]),
            end_ms=_timestamp_to_ms(g[4], g[5], g[6], g[7]),
            text=text,
        ))
    return entries


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
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    title TEXT,
    season INTEGER,
    episode INTEGER,
    subtitle_source TEXT DEFAULT 'whisper'
);

CREATE TABLE IF NOT EXISTS subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT REFERENCES episodes(id),
    start_ms INTEGER,
    end_ms INTEGER,
    text TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS subtitles_fts USING fts5(
    text,
    content='subtitles',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
"""


class Database:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(SCHEMA)

    def close(self):
        self._conn.close()

    def upsert_episode(
        self, episode_id: str, title: str | None, season: int, episode: int,
    ):
        self._conn.execute(
            """
            INSERT INTO episodes (id, title, season, episode, subtitle_source)
            VALUES (?, ?, ?, ?, 'whisper')
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                season=excluded.season,
                episode=excluded.episode,
                subtitle_source='whisper'
            """,
            (episode_id, title, season, episode),
        )
        self._conn.commit()

    def insert_subtitles(self, episode_id: str, entries: list[SubtitleEntry]):
        with self._conn:
            self._conn.execute(
                "DELETE FROM subtitles WHERE episode_id = ?", (episode_id,)
            )
            for entry in entries:
                self._conn.execute(
                    "INSERT INTO subtitles (episode_id, start_ms, end_ms, text) VALUES (?, ?, ?, ?)",
                    (episode_id, entry.start_ms, entry.end_ms, entry.text),
                )
            self._conn.execute(
                "INSERT INTO subtitles_fts(subtitles_fts) VALUES('rebuild')"
            )


# ---------------------------------------------------------------------------
# Episode / frame helpers
# ---------------------------------------------------------------------------

EPISODE_PATTERN = re.compile(r"S(\d{2})E(\d{2})", re.IGNORECASE)
FRAME_EXTENSIONS = {".jpg", ".jpeg", ".webp", ".png"}


def count_frames(frames_dir: str, episode_id: str) -> int:
    """Count frames for an episode. Supports both layouts:
    - Nested: frames_dir/S01/E01/frame_*.jpg
    - Flat:   frames_dir/S01E01/frame_*.webp
    """
    match = EPISODE_PATTERN.match(episode_id)
    if not match:
        return 0

    candidates = [
        os.path.join(frames_dir, f"S{int(match.group(1)):02d}", f"E{int(match.group(2)):02d}"),
        os.path.join(frames_dir, episode_id),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return sum(
                1 for f in os.listdir(path)
                if f.startswith("frame_") and os.path.splitext(f)[1] in FRAME_EXTENSIONS
            )
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_srt_files(subs_dir: str) -> list[tuple[str, str, int, int]]:
    results = []
    for filename in sorted(os.listdir(subs_dir)):
        if not filename.endswith(".srt"):
            continue
        match = EPISODE_PATTERN.search(filename)
        if not match:
            print(f"  Skipping {filename}: could not parse episode ID", file=sys.stderr)
            continue
        season = int(match.group(1))
        episode = int(match.group(2))
        episode_id = f"S{season:02d}E{episode:02d}"
        results.append((os.path.join(subs_dir, filename), episode_id, season, episode))
    return results


def process_episode(
    srt_path: str,
    episode_id: str,
    season: int,
    episode: int,
    db: Database,
    frames_dir: str | None,
) -> bool:
    try:
        entries = parse_srt(srt_path)
        entries = clean_srt(entries)

        if not entries:
            print(f"[{episode_id}] WARNING: No subtitles after cleaning", file=sys.stderr)
            return False

        db.upsert_episode(episode_id, None, season, episode)
        db.insert_subtitles(episode_id, entries)

        msg = f"[{episode_id}] {len(entries)} subtitles indexed"
        if frames_dir:
            fc = count_frames(frames_dir, episode_id)
            msg += f", {fc} frames"
            if fc == 0:
                msg += " (WARNING: no frames!)"
        print(msg)
        return True
    except Exception as e:
        print(f"[{episode_id}] ERROR: {e}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SQLite database from SRT subtitles")
    parser.add_argument("subs_dir", help="Directory with SRT files (e.g. S01E01.srt)")
    parser.add_argument("--frames-dir", help="Frames directory for verification")
    parser.add_argument("--db-path", default="data/simpsonizado.db", help="SQLite path (default: data/simpsonizado.db)")

    args = parser.parse_args()
    if not os.path.isdir(args.subs_dir):
        parser.error(f"Subs directory not found: {args.subs_dir}")

    os.makedirs(os.path.dirname(args.db_path) or ".", exist_ok=True)

    srt_files = find_srt_files(args.subs_dir)
    if not srt_files:
        print("No SRT files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(srt_files)} SRT files. Building database at {args.db_path}...")
    db = Database(args.db_path)

    succeeded = 0
    failed = 0
    for srt_path, episode_id, season, episode in srt_files:
        if process_episode(srt_path, episode_id, season, episode, db, args.frames_dir):
            succeeded += 1
        else:
            failed += 1

    db.close()
    print(f"\nComplete: {succeeded} succeeded, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
