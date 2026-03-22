import os
import subprocess

import pytest

from pipeline.db import Database
from pipeline.extract import process_episode


@pytest.fixture(autouse=True)
def _require_libwebp():
    """Skip integration tests if FFmpeg lacks libwebp encoder."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.skip("FFmpeg not installed")
    if result.returncode != 0 or "libwebp" not in result.stdout:
        pytest.skip("FFmpeg libwebp encoder not available")


@pytest.fixture
def synthetic_mkv(tmp_path):
    """Create a tiny .mkv with embedded subtitles for testing."""
    # Create a 3-second .srt
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(
        "1\n00:00:00,500 --> 00:00:02,000\nHola, soy Homero.\n\n"
        "2\n00:00:02,500 --> 00:00:03,000\n¡Ay, caramba!\n",
        encoding="utf-8",
    )

    # Generate a 3-second color video with embedded subtitles
    mkv_path = str(tmp_path / "S01E01.mkv")
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=yellow:size=320x240:d=3:rate=10",
            "-i", str(srt_path),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:s", "srt",
            "-metadata:s:s:0", "language=spa",
            mkv_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"FFmpeg not available or failed: {result.stderr}")

    return mkv_path


def test_full_pipeline(synthetic_mkv, tmp_path):
    frames_dir = str(tmp_path / "frames")
    db_path = str(tmp_path / "test.db")

    ok = process_episode(
        input_path=synthetic_mkv,
        episode_id="S01E01",
        frames_dir=frames_dir,
        db_path=db_path,
    )

    assert ok is True

    # Verify frames were created
    episode_dir = os.path.join(frames_dir, "S01E01")
    frames = [f for f in os.listdir(episode_dir) if f.startswith("frame_")]
    assert len(frames) > 0

    # Verify .done marker
    assert os.path.exists(os.path.join(episode_dir, ".done"))

    # Verify database
    db = Database(db_path)

    episode = db.execute("SELECT * FROM episodes WHERE id = 'S01E01'").fetchone()
    assert episode is not None
    assert episode[3] == 1  # episode number

    subs = db.execute(
        "SELECT * FROM subtitles WHERE episode_id = 'S01E01'"
    ).fetchall()
    assert len(subs) == 2

    # Verify FTS search works
    results = db.search('"Homero"')
    assert len(results) == 1
    assert "Homero" in results[0]["text"]

    results = db.search('"caramba"')
    assert len(results) == 1

    db.close()


def test_resumability_skips_completed(synthetic_mkv, tmp_path):
    frames_dir = str(tmp_path / "frames")
    db_path = str(tmp_path / "test.db")

    # First run
    process_episode(synthetic_mkv, "S01E01", frames_dir, db_path)

    # Second run should skip
    ok = process_episode(synthetic_mkv, "S01E01", frames_dir, db_path)
    assert ok is True
