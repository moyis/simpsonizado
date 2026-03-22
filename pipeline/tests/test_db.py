from pipeline.db import Database
from pipeline.subtitle_parser import SubtitleEntry


def test_creates_schema(tmp_db):
    db = Database(tmp_db)

    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in tables}

    assert "episodes" in table_names
    assert "subtitles" in table_names
    assert "subtitles_fts" in table_names
    db.close()


def test_inserts_episode(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode(
        episode_id="S01E01",
        title="Especial de Navidad",
        season=1,
        episode=1,
        fps=23.976,
        total_frames=31254,
    )

    row = db.execute("SELECT * FROM episodes WHERE id = 'S01E01'").fetchone()

    assert row is not None
    assert row[0] == "S01E01"
    assert row[1] == "Especial de Navidad"
    assert row[4] == 23.976
    db.close()


def test_upsert_episode_overwrites(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", "Old Title", 1, 1, 23.976, 31254)
    db.upsert_episode("S01E01", "New Title", 1, 1, 24.0, 31300)

    row = db.execute("SELECT title, fps FROM episodes WHERE id = 'S01E01'").fetchone()

    assert row[0] == "New Title"
    assert row[1] == 24.0
    db.close()


def test_inserts_subtitles_and_rebuilds_fts(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)

    entries = [
        SubtitleEntry(start_ms=1000, end_ms=3500, text="Hola, soy Homero Simpson."),
        SubtitleEntry(start_ms=5200, end_ms=7800, text="¡Ay, caramba!"),
    ]
    db.insert_subtitles("S01E01", entries, fps=24.0)

    rows = db.execute(
        "SELECT * FROM subtitles WHERE episode_id = 'S01E01'"
    ).fetchall()

    assert len(rows) == 2
    assert rows[0][4] == "Hola, soy Homero Simpson."
    db.close()


def test_fts_search_exact_phrase(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)
    db.insert_subtitles(
        "S01E01",
        [
            SubtitleEntry(1000, 3500, "Hola, soy Homero Simpson."),
            SubtitleEntry(5200, 7800, "¡Ay, caramba!"),
            SubtitleEntry(10000, 12500, "No he sido yo."),
        ],
        fps=24.0,
    )

    results = db.search('"Homero Simpson"')

    assert len(results) == 1
    assert results[0]["text"] == "Hola, soy Homero Simpson."
    assert results[0]["episode_id"] == "S01E01"
    db.close()


def test_fts_search_keywords_with_and(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)
    db.insert_subtitles(
        "S01E01",
        [
            SubtitleEntry(1000, 3500, "Homero bebe cerveza en el bar."),
            SubtitleEntry(5200, 7800, "Bart bebe agua."),
            SubtitleEntry(10000, 12500, "Homero come donas."),
        ],
        fps=24.0,
    )

    results = db.search("Homero AND cerveza")

    assert len(results) == 1
    assert "cerveza" in results[0]["text"]
    db.close()


def test_fts_search_diacritics_insensitive(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)
    db.insert_subtitles(
        "S01E01",
        [SubtitleEntry(1000, 3500, "Había una vez un señor.")],
        fps=24.0,
    )

    results = db.search('"habia una vez"')

    assert len(results) == 1
    db.close()


def test_insert_subtitles_is_idempotent(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)

    entries = [SubtitleEntry(1000, 3500, "Hola.")]
    db.insert_subtitles("S01E01", entries, fps=24.0)
    db.insert_subtitles("S01E01", entries, fps=24.0)

    rows = db.execute(
        "SELECT COUNT(*) FROM subtitles WHERE episode_id = 'S01E01'"
    ).fetchone()

    assert rows[0] == 1
    db.close()


def test_frame_numbers_are_1_based(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)
    db.insert_subtitles(
        "S01E01",
        [SubtitleEntry(0, 1000, "First line.")],
        fps=24.0,
    )

    row = db.execute(
        "SELECT start_frame, end_frame FROM subtitles WHERE episode_id = 'S01E01'"
    ).fetchone()

    assert row[0] == 1  # frame 0 at time 0 becomes frame 1 (1-based)
    assert row[1] == 25  # floor(1.0 * 24) + 1 = 25
    db.close()


def test_search_returns_frame_range(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)
    db.insert_subtitles(
        "S01E01",
        [SubtitleEntry(1000, 3500, "Hola mundo.")],
        fps=24.0,
    )

    results = db.search("Hola")

    assert len(results) == 1
    assert "start_frame" in results[0]
    assert "end_frame" in results[0]
    assert results[0]["start_frame"] == 25  # floor(1.0 * 24) + 1
    assert results[0]["end_frame"] == 85  # floor(3.5 * 24) + 1
    db.close()


def test_upsert_episode_stores_subtitle_source(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000, subtitle_source="whisper")
    row = db.execute(
        "SELECT subtitle_source FROM episodes WHERE id = 'S01E01'"
    ).fetchone()
    assert row[0] == "whisper"
    db.close()


def test_upsert_episode_defaults_subtitle_source_to_embedded(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)
    row = db.execute(
        "SELECT subtitle_source FROM episodes WHERE id = 'S01E01'"
    ).fetchone()
    assert row[0] == "embedded"
    db.close()


def test_upsert_episode_updates_subtitle_source(tmp_db):
    db = Database(tmp_db)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000)
    db.upsert_episode("S01E01", None, 1, 1, 24.0, 31000, subtitle_source="whisper")
    row = db.execute(
        "SELECT subtitle_source FROM episodes WHERE id = 'S01E01'"
    ).fetchone()
    assert row[0] == "whisper"
    db.close()
