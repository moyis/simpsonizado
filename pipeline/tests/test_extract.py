import os
from unittest.mock import MagicMock, patch, call

import pytest

from pipeline.extract import parse_episode_id, process_episode, is_episode_done, mark_episode_done


def test_parse_episode_id_from_standard_name():
    assert parse_episode_id("S01E01.mkv") == "S01E01"


def test_parse_episode_id_from_complex_name():
    assert parse_episode_id("The.Simpsons.S03E12.720p.mkv") == "S03E12"


def test_parse_episode_id_returns_none_for_no_match():
    assert parse_episode_id("random_video.mkv") is None


def test_is_episode_done_false_when_no_marker(tmp_frames_dir):
    episode_dir = os.path.join(tmp_frames_dir, "S01E01")
    os.makedirs(episode_dir, exist_ok=True)

    assert is_episode_done(tmp_frames_dir, "S01E01") is False


def test_is_episode_done_true_when_marker_exists(tmp_frames_dir):
    episode_dir = os.path.join(tmp_frames_dir, "S01E01")
    os.makedirs(episode_dir, exist_ok=True)
    with open(os.path.join(episode_dir, ".done"), "w") as f:
        f.write("")

    assert is_episode_done(tmp_frames_dir, "S01E01") is True


def test_mark_episode_done_creates_marker(tmp_frames_dir):
    episode_dir = os.path.join(tmp_frames_dir, "S01E01")
    os.makedirs(episode_dir, exist_ok=True)

    mark_episode_done(tmp_frames_dir, "S01E01")

    assert os.path.exists(os.path.join(episode_dir, ".done"))


@patch("pipeline.extract.frame_extractor")
@patch("pipeline.extract.Database")
def test_process_episode_skips_when_done(mock_db_cls, mock_ffmpeg, tmp_path):
    frames_dir = str(tmp_path / "frames")
    episode_dir = os.path.join(frames_dir, "S01E01")
    os.makedirs(episode_dir)
    with open(os.path.join(episode_dir, ".done"), "w") as f:
        f.write("")

    process_episode(
        input_path="/fake/S01E01.mkv",
        episode_id="S01E01",
        frames_dir=frames_dir,
        db_path=str(tmp_path / "test.db"),
    )

    mock_ffmpeg.extract_frames_for_subtitles.assert_not_called()
    mock_ffmpeg.detect_fps.assert_not_called()
    mock_db_cls.assert_not_called()


def _create_fake_frames(episode_dir, count=5):
    """Helper to create fake frame files for mocked tests."""
    os.makedirs(episode_dir, exist_ok=True)
    for i in range(1, count + 1):
        with open(os.path.join(episode_dir, f"frame_{i:06d}.webp"), "w") as f:
            f.write("")
        with open(os.path.join(episode_dir, f"thumb_{i:06d}.webp"), "w") as f:
            f.write("")


@patch("pipeline.extract.frame_extractor")
@patch("pipeline.extract.Database")
def test_process_episode_full_flow(mock_db_cls, mock_ffmpeg, tmp_path):
    frames_dir = str(tmp_path / "frames")
    db_path = str(tmp_path / "test.db")
    episode_dir = os.path.join(frames_dir, "S01E01")
    mock_ffmpeg.detect_fps.return_value = 24.0
    mock_ffmpeg.find_spanish_subtitle_track.return_value = 0
    mock_ffmpeg.extract_subtitles.return_value = str(tmp_path / "subs.srt")

    # Mock extract_frames_for_subtitles to create fake frame files
    def fake_extract(input_path, output_dir, fps, entries):
        _create_fake_frames(output_dir, count=62)
        return 62

    mock_ffmpeg.extract_frames_for_subtitles.side_effect = fake_extract

    # Create a fake .srt so subtitle_parser can read it
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHola.\n", encoding="utf-8"
    )

    process_episode(
        input_path="/fake/S01E01.mkv",
        episode_id="S01E01",
        frames_dir=frames_dir,
        db_path=db_path,
    )

    mock_ffmpeg.detect_fps.assert_called_once()
    mock_ffmpeg.find_spanish_subtitle_track.assert_called_once()
    mock_ffmpeg.extract_frames_for_subtitles.assert_called_once()
    mock_db_cls.return_value.upsert_episode.assert_called_once()
    mock_db_cls.return_value.insert_subtitles.assert_called_once()
    # Verify .done marker was created
    assert os.path.exists(os.path.join(episode_dir, ".done"))


@patch("pipeline.extract.frame_extractor")
@patch("pipeline.extract.Database")
def test_process_episode_cleans_partial_extraction(mock_db_cls, mock_ffmpeg, tmp_path):
    """If episode dir exists without .done marker, it should be deleted and re-extracted."""
    frames_dir = str(tmp_path / "frames")
    episode_dir = os.path.join(frames_dir, "S01E01")

    # Create partial extraction (dir exists, no .done marker)
    os.makedirs(episode_dir)
    with open(os.path.join(episode_dir, "frame_000001.webp"), "w") as f:
        f.write("partial")

    mock_ffmpeg.detect_fps.return_value = 24.0
    mock_ffmpeg.find_spanish_subtitle_track.return_value = 0
    mock_ffmpeg.extract_subtitles.return_value = str(tmp_path / "subs.srt")

    def fake_extract(inp, out, fps, entries):
        _create_fake_frames(out, 62)
        return 62

    mock_ffmpeg.extract_frames_for_subtitles.side_effect = fake_extract

    srt_path = tmp_path / "subs.srt"
    srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nHola.\n", encoding="utf-8")

    ok = process_episode("/fake/S01E01.mkv", "S01E01", frames_dir, str(tmp_path / "test.db"))

    assert ok is True
    # Should have re-extracted (old partial file gone, new files present)
    mock_ffmpeg.extract_frames_for_subtitles.assert_called_once()


@patch("pipeline.extract.frame_extractor")
@patch("pipeline.extract.Database")
def test_process_episode_passes_title(mock_db_cls, mock_ffmpeg, tmp_path):
    """Title should be propagated to upsert_episode."""
    frames_dir = str(tmp_path / "frames")
    mock_ffmpeg.detect_fps.return_value = 24.0
    mock_ffmpeg.find_spanish_subtitle_track.return_value = 0
    mock_ffmpeg.extract_subtitles.return_value = str(tmp_path / "subs.srt")

    def fake_extract(inp, out, fps, entries):
        _create_fake_frames(out, 62)
        return 62

    mock_ffmpeg.extract_frames_for_subtitles.side_effect = fake_extract

    srt_path = tmp_path / "subs.srt"
    srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nHola.\n", encoding="utf-8")

    process_episode(
        "/fake/S01E01.mkv", "S01E01", frames_dir, str(tmp_path / "test.db"),
        title="Especial de Navidad",
    )

    call_args = mock_db_cls.return_value.upsert_episode.call_args
    assert call_args[0][1] == "Especial de Navidad"


@patch("pipeline.extract.frame_extractor")
@patch("pipeline.extract.Database")
def test_process_episode_uses_whisper_srt_when_available(mock_db_cls, mock_ffmpeg, tmp_path):
    frames_dir = str(tmp_path / "frames")
    whisper_dir = str(tmp_path / "whisper_srt")
    os.makedirs(whisper_dir)

    # Create Whisper SRT
    whisper_srt = os.path.join(whisper_dir, "S01E01.srt")
    with open(whisper_srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nTienes una rosca o no?\n")

    mock_ffmpeg.detect_fps.return_value = 24.0

    def fake_extract(inp, out, fps, entries):
        _create_fake_frames(out, 62)
        return 62

    mock_ffmpeg.extract_frames_for_subtitles.side_effect = fake_extract

    process_episode(
        input_path="/fake/S01E01.mkv",
        episode_id="S01E01",
        frames_dir=frames_dir,
        db_path=str(tmp_path / "test.db"),
        whisper_srt_dir=whisper_dir,
    )

    # Should NOT call find_spanish_subtitle_track or extract_subtitles
    mock_ffmpeg.find_spanish_subtitle_track.assert_not_called()
    mock_ffmpeg.extract_subtitles.assert_not_called()

    # Should call upsert_episode with subtitle_source="whisper"
    upsert_call = mock_db_cls.return_value.upsert_episode.call_args
    assert upsert_call[0][6] == "whisper"  # 7th positional arg


@patch("pipeline.extract.frame_extractor")
@patch("pipeline.extract.Database")
def test_process_episode_falls_back_to_embedded(mock_db_cls, mock_ffmpeg, tmp_path):
    frames_dir = str(tmp_path / "frames")
    whisper_dir = str(tmp_path / "whisper_srt")
    os.makedirs(whisper_dir)
    # No Whisper SRT file exists

    mock_ffmpeg.detect_fps.return_value = 24.0
    mock_ffmpeg.find_spanish_subtitle_track.return_value = 0
    mock_ffmpeg.extract_subtitles.return_value = str(tmp_path / "subs.srt")

    def fake_extract(inp, out, fps, entries):
        _create_fake_frames(out, 62)
        return 62

    mock_ffmpeg.extract_frames_for_subtitles.side_effect = fake_extract

    srt_path = tmp_path / "subs.srt"
    srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nHola.\n", encoding="utf-8")

    process_episode(
        input_path="/fake/S01E01.mkv",
        episode_id="S01E01",
        frames_dir=frames_dir,
        db_path=str(tmp_path / "test.db"),
        whisper_srt_dir=whisper_dir,
    )

    # Should call embedded subtitle extraction
    mock_ffmpeg.find_spanish_subtitle_track.assert_called_once()

    # Should call upsert_episode with subtitle_source="embedded"
    upsert_call = mock_db_cls.return_value.upsert_episode.call_args
    assert upsert_call[0][6] == "embedded"


@patch("pipeline.extract.frame_extractor")
@patch("pipeline.extract.Database")
def test_process_episode_no_whisper_flag_ignores_whisper_srt(mock_db_cls, mock_ffmpeg, tmp_path):
    frames_dir = str(tmp_path / "frames")
    whisper_dir = str(tmp_path / "whisper_srt")
    os.makedirs(whisper_dir)

    # Create Whisper SRT (should be ignored)
    whisper_srt = os.path.join(whisper_dir, "S01E01.srt")
    with open(whisper_srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nWhisper text.\n")

    mock_ffmpeg.detect_fps.return_value = 24.0
    mock_ffmpeg.find_spanish_subtitle_track.return_value = 0
    mock_ffmpeg.extract_subtitles.return_value = str(tmp_path / "subs.srt")

    def fake_extract(inp, out, fps, entries):
        _create_fake_frames(out, 62)
        return 62

    mock_ffmpeg.extract_frames_for_subtitles.side_effect = fake_extract

    srt_path = tmp_path / "subs.srt"
    srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nEmbedded.\n", encoding="utf-8")

    process_episode(
        input_path="/fake/S01E01.mkv",
        episode_id="S01E01",
        frames_dir=frames_dir,
        db_path=str(tmp_path / "test.db"),
        whisper_srt_dir=whisper_dir,
        no_whisper=True,
    )

    # Should use embedded even though whisper SRT exists
    mock_ffmpeg.find_spanish_subtitle_track.assert_called_once()
