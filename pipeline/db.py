from __future__ import annotations

import math
import sqlite3

from pipeline.subtitle_parser import SubtitleEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    title TEXT,
    season INTEGER,
    episode INTEGER,
    fps REAL,
    total_frames INTEGER,
    subtitle_source TEXT DEFAULT 'embedded'
);

CREATE TABLE IF NOT EXISTS subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT REFERENCES episodes(id),
    start_ms INTEGER,
    end_ms INTEGER,
    text TEXT,
    start_frame INTEGER,
    end_frame INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS subtitles_fts USING fts5(
    text,
    content='subtitles',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
"""


def _compute_frame(ms: int, fps: float) -> int:
    return math.floor((ms / 1000) * fps) + 1


class Database:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Add columns that may be missing in existing databases."""
        try:
            self._conn.execute(
                "ALTER TABLE episodes ADD COLUMN subtitle_source TEXT DEFAULT 'embedded'"
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def close(self):
        self._conn.close()

    def upsert_episode(
        self,
        episode_id: str,
        title: str | None,
        season: int,
        episode: int,
        fps: float,
        total_frames: int,
        subtitle_source: str = "embedded",
    ):
        self._conn.execute(
            """
            INSERT INTO episodes (id, title, season, episode, fps, total_frames, subtitle_source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                season=excluded.season,
                episode=excluded.episode,
                fps=excluded.fps,
                total_frames=excluded.total_frames,
                subtitle_source=excluded.subtitle_source
            """,
            (episode_id, title, season, episode, fps, total_frames, subtitle_source),
        )
        self._conn.commit()

    def insert_subtitles(
        self,
        episode_id: str,
        entries: list[SubtitleEntry],
        fps: float,
    ):
        with self._conn:
            self._conn.execute(
                "DELETE FROM subtitles WHERE episode_id = ?", (episode_id,)
            )

            for entry in entries:
                start_frame = _compute_frame(entry.start_ms, fps)
                end_frame = _compute_frame(entry.end_ms, fps)
                self._conn.execute(
                    """
                    INSERT INTO subtitles (episode_id, start_ms, end_ms, text, start_frame, end_frame)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        episode_id,
                        entry.start_ms,
                        entry.end_ms,
                        entry.text,
                        start_frame,
                        end_frame,
                    ),
                )

            self._conn.execute(
                "INSERT INTO subtitles_fts(subtitles_fts) VALUES('rebuild')"
            )

    def search(self, query: str, limit: int = 20) -> list[dict]:
        cursor = self._conn.execute(
            """
            SELECT s.episode_id, s.text, s.start_ms, s.end_ms,
                   s.start_frame, s.end_frame
            FROM subtitles_fts fts
            JOIN subtitles s ON s.id = fts.rowid
            WHERE subtitles_fts MATCH ?
            ORDER BY bm25(subtitles_fts)
            LIMIT ?
            """,
            (query, limit),
        )
        return [
            {
                "episode_id": row[0],
                "text": row[1],
                "start_ms": row[2],
                "end_ms": row[3],
                "start_frame": row[4],
                "end_frame": row[5],
            }
            for row in cursor.fetchall()
        ]
