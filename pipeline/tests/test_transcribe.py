import os
from unittest.mock import MagicMock, patch

from pipeline.subtitle_parser import SubtitleEntry
from pipeline.transcribe import process_single_episode


@patch("pipeline.transcribe.clean_srt")
@patch("pipeline.transcribe.segments_to_srt")
@patch("pipeline.transcribe.transcriber")
def test_process_single_episode_creates_srt(
    mock_transcriber, mock_segments_to_srt, mock_clean_srt, tmp_path
):
    output_dir = str(tmp_path / "whisper_srt")
    os.makedirs(output_dir)

    mock_transcriber.find_spanish_audio_track.return_value = "0:a:1"
    mock_transcriber.transcribe_audio.return_value = [
        SubtitleEntry(1000, 3000, "Hola")
    ]
    mock_clean_srt.return_value = [SubtitleEntry(1000, 3000, "Hola")]
    mock_model = MagicMock()

    result = process_single_episode(
        "/fake/S01E01.mkv", output_dir, mock_model, force=False
    )

    assert result is True
    mock_transcriber.find_spanish_audio_track.assert_called_once_with(
        "/fake/S01E01.mkv"
    )
    mock_transcriber.extract_audio.assert_called_once()
    mock_transcriber.transcribe_audio.assert_called_once()
    mock_clean_srt.assert_called_once()
    mock_segments_to_srt.assert_called_once()

    # Verify output path uses the episode ID
    srt_path = mock_segments_to_srt.call_args[0][1]
    assert srt_path == os.path.join(output_dir, "S01E01.srt")


@patch("pipeline.transcribe.clean_srt")
@patch("pipeline.transcribe.segments_to_srt")
@patch("pipeline.transcribe.transcriber")
def test_process_single_episode_skips_existing(
    mock_transcriber, mock_segments_to_srt, mock_clean_srt, tmp_path
):
    output_dir = str(tmp_path / "whisper_srt")
    os.makedirs(output_dir)

    # Create existing SRT
    srt_path = os.path.join(output_dir, "S01E01.srt")
    with open(srt_path, "w") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nHola\n")

    mock_model = MagicMock()
    result = process_single_episode(
        "/fake/S01E01.mkv", output_dir, mock_model, force=False
    )

    assert result is True
    mock_transcriber.find_spanish_audio_track.assert_not_called()
    mock_transcriber.extract_audio.assert_not_called()


@patch("pipeline.transcribe.clean_srt")
@patch("pipeline.transcribe.segments_to_srt")
@patch("pipeline.transcribe.transcriber")
def test_process_single_episode_force_reprocesses(
    mock_transcriber, mock_segments_to_srt, mock_clean_srt, tmp_path
):
    output_dir = str(tmp_path / "whisper_srt")
    os.makedirs(output_dir)

    # Create existing SRT
    srt_path = os.path.join(output_dir, "S01E01.srt")
    with open(srt_path, "w") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nHola\n")

    mock_transcriber.find_spanish_audio_track.return_value = "0:a:0"
    mock_transcriber.transcribe_audio.return_value = [
        SubtitleEntry(1000, 3000, "Hola amigo")
    ]
    mock_clean_srt.return_value = [SubtitleEntry(1000, 3000, "Hola amigo")]
    mock_model = MagicMock()

    result = process_single_episode(
        "/fake/S01E01.mkv", output_dir, mock_model, force=True
    )

    assert result is True
    mock_transcriber.find_spanish_audio_track.assert_called_once()
    mock_transcriber.transcribe_audio.assert_called_once()


@patch("pipeline.transcribe.transcriber")
def test_process_single_episode_returns_false_no_audio(mock_transcriber, tmp_path):
    output_dir = str(tmp_path / "whisper_srt")
    os.makedirs(output_dir)

    mock_transcriber.find_spanish_audio_track.return_value = None
    mock_model = MagicMock()

    result = process_single_episode(
        "/fake/S01E01.mkv", output_dir, mock_model, force=False
    )

    assert result is False
    mock_transcriber.extract_audio.assert_not_called()


@patch("pipeline.transcribe.transcriber")
def test_process_single_episode_returns_false_on_exception(
    mock_transcriber, tmp_path
):
    output_dir = str(tmp_path / "whisper_srt")
    os.makedirs(output_dir)

    mock_transcriber.find_spanish_audio_track.side_effect = RuntimeError("ffprobe fail")
    mock_model = MagicMock()

    result = process_single_episode(
        "/fake/S01E01.mkv", output_dir, mock_model, force=False
    )

    assert result is False


def test_process_single_episode_returns_false_for_unparseable_filename(tmp_path):
    output_dir = str(tmp_path / "whisper_srt")
    os.makedirs(output_dir)

    mock_model = MagicMock()
    result = process_single_episode(
        "/fake/random_video.mkv", output_dir, mock_model, force=False
    )

    assert result is False


@patch("pipeline.transcribe.parse_episode_id")
def test_main_single_file(mock_parse_id, tmp_path):
    """Test main() CLI parsing with --input flag."""
    from unittest.mock import patch as _patch

    mock_parse_id.return_value = "S01E01"
    output_dir = str(tmp_path / "whisper_srt")

    with _patch(
        "sys.argv",
        [
            "transcribe",
            "--input", "/fake/S01E01.mkv",
            "--output-dir", output_dir,
            "--model", "tiny",
        ],
    ), _patch(
        "pipeline.transcribe.process_single_episode", return_value=True
    ) as mock_process, _patch(
        "pipeline.transcribe.load_model"
    ) as mock_load:
        from pipeline.transcribe import main

        mock_load.return_value = MagicMock()
        main()

        mock_process.assert_called_once()
        call_args = mock_process.call_args
        assert call_args[0][0] == "/fake/S01E01.mkv"
        assert call_args[0][1] == output_dir


@patch("pipeline.transcribe.parse_episode_id")
def test_main_batch_mode(mock_parse_id, tmp_path):
    """Test main() CLI parsing with --input-dir flag."""
    from unittest.mock import patch as _patch

    input_dir = str(tmp_path / "episodes")
    os.makedirs(input_dir)

    # Create fake mkv files
    for name in ["S01E01.mkv", "S01E02.mkv"]:
        with open(os.path.join(input_dir, name), "w") as f:
            f.write("")

    mock_parse_id.side_effect = lambda f: f.replace(".mkv", "")
    output_dir = str(tmp_path / "whisper_srt")

    with _patch(
        "sys.argv",
        [
            "transcribe",
            "--input-dir", input_dir,
            "--output-dir", output_dir,
            "--model", "tiny",
            "--workers", "1",
        ],
    ), _patch(
        "pipeline.transcribe.process_single_episode", return_value=True
    ) as mock_process, _patch(
        "pipeline.transcribe.load_model"
    ) as mock_load:
        from pipeline.transcribe import main

        mock_load.return_value = MagicMock()
        main()

        assert mock_process.call_count == 2


def test_main_warns_about_workers(tmp_path, caplog):
    """Test that main() warns when using multiple workers with GPU."""
    import logging
    from unittest.mock import patch as _patch

    output_dir = str(tmp_path / "whisper_srt")

    with _patch(
        "sys.argv",
        [
            "transcribe",
            "--input", "/fake/S01E01.mkv",
            "--output-dir", output_dir,
            "--model", "medium",
            "--workers", "3",
        ],
    ), _patch(
        "pipeline.transcribe.process_single_episode", return_value=True
    ), _patch(
        "pipeline.transcribe.load_model"
    ) as mock_load, caplog.at_level(logging.WARNING):
        from pipeline.transcribe import main

        mock_load.return_value = "mlx-community/whisper-medium-mlx"
        main()

        assert any("workers" in r.message.lower() for r in caplog.records)
