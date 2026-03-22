from unittest.mock import MagicMock, patch

import pytest

from pipeline.subtitle_parser import SubtitleEntry
from pipeline.transcriber import (
    MODEL_REPOS,
    _ms_to_srt_timestamp,
    _split_segment_by_silence,
    extract_audio,
    find_spanish_audio_track,
    load_model,
    segments_to_srt,
    transcribe_audio,
)


# --- find_spanish_audio_track ---


@patch("pipeline.transcriber.subprocess.run")
def test_finds_spanish_audio_track_by_spa(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":1,"tags":{"language":"spa"}},'
        '{"index":2,"tags":{"language":"eng"}}'
        "]}"
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track == "0:a:0"


@patch("pipeline.transcriber.subprocess.run")
def test_finds_spanish_audio_track_by_es(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":1,"tags":{"language":"eng"}},'
        '{"index":2,"tags":{"language":"es"}}'
        "]}"
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track == "0:a:1"


@patch("pipeline.transcriber.subprocess.run")
def test_finds_spanish_audio_track_by_esp(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":1,"tags":{"language":"esp"}}'
        "]}"
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track == "0:a:0"


@patch("pipeline.transcriber.subprocess.run")
def test_skips_commentary_audio_track(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":1,"tags":{"language":"spa","title":"Commentary"}},'
        '{"index":2,"tags":{"language":"spa","title":"Español"}}'
        "]}"
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track == "0:a:1"


@patch("pipeline.transcriber.subprocess.run")
def test_skips_comentario_audio_track(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":1,"tags":{"language":"spa","title":"Comentario del director"}},'
        '{"index":2,"tags":{"language":"spa","title":"Audio principal"}}'
        "]}"
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track == "0:a:1"


@patch("pipeline.transcriber.subprocess.run")
def test_skips_director_audio_track(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":1,"tags":{"language":"spa","title":"Director"}},'
        '{"index":2,"tags":{"language":"spa","title":"Español Latino"}}'
        "]}"
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track == "0:a:1"


@patch("pipeline.transcriber.subprocess.run")
def test_returns_none_when_no_spanish_audio(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":1,"tags":{"language":"eng"}},'
        '{"index":2,"tags":{"language":"fre"}}'
        "]}"
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track is None


@patch("pipeline.transcriber.subprocess.run")
def test_returns_none_when_ffprobe_fails(mock_run):
    mock_run.return_value = MagicMock(stdout="", returncode=1, stderr="error")

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track is None


@patch("pipeline.transcriber.subprocess.run")
def test_returns_none_when_no_streams(mock_run):
    mock_run.return_value = MagicMock(stdout='{"streams":[]}', returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track is None


@patch("pipeline.transcriber.subprocess.run")
def test_handles_missing_tags_gracefully(mock_run):
    ffprobe_output = '{"streams":[{"index":1},{"index":2,"tags":{"language":"spa"}}]}'
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_audio_track("/path/to/episode.mkv")

    assert track == "0:a:1"


# --- extract_audio ---


@patch("pipeline.transcriber.subprocess.run")
def test_extract_audio_calls_ffmpeg(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    extract_audio("/path/to/episode.mkv", "0:a:1", "/tmp/audio.wav")

    args = mock_run.call_args[0][0]
    assert args[0] == "ffmpeg"
    assert "-y" in args
    assert "-i" in args
    assert "/path/to/episode.mkv" in args
    assert "-map" in args
    assert "0:a:1" in args
    assert "-ar" in args
    assert "16000" in args
    assert "-ac" in args
    assert "1" in args
    assert "-c:a" in args
    assert "pcm_s16le" in args
    assert "/tmp/audio.wav" in args


@patch("pipeline.transcriber.subprocess.run")
def test_extract_audio_raises_on_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="encoding error")

    with pytest.raises(RuntimeError, match="extract audio"):
        extract_audio("/path/to/episode.mkv", "0:a:0", "/tmp/audio.wav")


# --- load_model ---


def test_load_model_returns_repo_path():
    repo = load_model("medium")

    assert repo == "mlx-community/whisper-medium-mlx"


def test_load_model_all_sizes():
    for size, expected_repo in MODEL_REPOS.items():
        assert load_model(size) == expected_repo


def test_load_model_raises_on_unknown_size():
    with pytest.raises(ValueError, match="Unknown model size"):
        load_model("nonexistent")


# --- _split_segment_by_silence ---


def test_split_keeps_segment_without_silence_gaps():
    segment = {
        "start": 1.0, "end": 3.0, "text": " Hola mundo",
        "words": [
            {"word": " Hola", "start": 1.0, "end": 1.5},
            {"word": " mundo", "start": 1.6, "end": 2.0},
        ],
    }

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 1
    assert entries[0].text == "Hola mundo"
    assert entries[0].start_ms == 1000
    assert entries[0].end_ms == 2000


def test_split_at_silence_gap():
    segment = {
        "start": 1.0, "end": 5.0, "text": " Hola Adiós",
        "words": [
            {"word": " Hola", "start": 1.0, "end": 1.5},
            {"word": " Adiós", "start": 3.0, "end": 3.5},  # 1500ms gap
        ],
    }

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 2
    assert entries[0] == SubtitleEntry(start_ms=1000, end_ms=1500, text="Hola")
    assert entries[1] == SubtitleEntry(start_ms=3000, end_ms=3500, text="Adiós")


def test_split_multiple_silence_gaps():
    segment = {
        "start": 0.0, "end": 8.0, "text": " Uno Dos Tres",
        "words": [
            {"word": " Uno", "start": 0.0, "end": 0.5},
            {"word": " Dos", "start": 2.0, "end": 2.5},  # 1500ms gap
            {"word": " Tres", "start": 4.0, "end": 4.5},  # 1500ms gap
        ],
    }

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 3
    assert entries[0].text == "Uno"
    assert entries[1].text == "Dos"
    assert entries[2].text == "Tres"


def test_split_gap_exactly_at_threshold_does_not_split():
    segment = {
        "start": 0.0, "end": 2.0, "text": " Hola mundo",
        "words": [
            {"word": " Hola", "start": 0.0, "end": 0.5},
            {"word": " mundo", "start": 0.899, "end": 1.5},  # 399ms gap
        ],
    }

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 1
    assert entries[0].text == "Hola mundo"


def test_split_gap_at_threshold_splits():
    segment = {
        "start": 0.0, "end": 2.0, "text": " Hola mundo",
        "words": [
            {"word": " Hola", "start": 0.0, "end": 0.5},
            {"word": " mundo", "start": 0.9, "end": 1.5},  # 400ms gap
        ],
    }

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 2


def test_split_fallback_without_words():
    segment = {"start": 1.0, "end": 3.0, "text": " Hola mundo"}

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 1
    assert entries[0] == SubtitleEntry(start_ms=1000, end_ms=3000, text="Hola mundo")


def test_split_skips_empty_text_without_words():
    segment = {"start": 1.0, "end": 3.0, "text": "   "}

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 0


def test_split_multiword_chunks():
    segment = {
        "start": 0.0, "end": 6.0, "text": " Hola amigo Adiós vecino",
        "words": [
            {"word": " Hola", "start": 0.0, "end": 0.3},
            {"word": " amigo", "start": 0.35, "end": 0.8},
            {"word": " Adiós", "start": 3.0, "end": 3.3},  # 2200ms gap
            {"word": " vecino", "start": 3.35, "end": 3.8},
        ],
    }

    entries = _split_segment_by_silence(segment)

    assert len(entries) == 2
    assert entries[0].text == "Hola amigo"
    assert entries[0].start_ms == 0
    assert entries[0].end_ms == 800
    assert entries[1].text == "Adiós vecino"
    assert entries[1].start_ms == 3000
    assert entries[1].end_ms == 3800


# --- transcribe_audio ---


@patch("pipeline.transcriber.mlx_whisper")
def test_transcribe_audio_returns_subtitle_entries(mock_mlx):
    mock_mlx.transcribe.return_value = {
        "text": "Hola mundo Adiós",
        "segments": [
            {
                "start": 1.5, "end": 3.2, "text": " Hola mundo",
                "words": [
                    {"word": " Hola", "start": 1.5, "end": 2.0},
                    {"word": " mundo", "start": 2.1, "end": 3.2},
                ],
            },
            {
                "start": 5.0, "end": 7.8, "text": "  Adiós  ",
                "words": [
                    {"word": "  Adiós  ", "start": 5.0, "end": 7.8},
                ],
            },
        ],
        "language": "es",
    }

    entries = transcribe_audio("/tmp/audio.wav", "mlx-community/whisper-medium-mlx")

    assert len(entries) == 2
    assert entries[0] == SubtitleEntry(start_ms=1500, end_ms=3200, text="Hola mundo")
    assert entries[1] == SubtitleEntry(start_ms=5000, end_ms=7800, text="Adiós")


@patch("pipeline.transcriber.mlx_whisper")
def test_transcribe_audio_splits_at_silence(mock_mlx):
    mock_mlx.transcribe.return_value = {
        "text": "Speaker one Speaker two",
        "segments": [
            {
                "start": 0.0, "end": 5.0, "text": " Speaker one Speaker two",
                "words": [
                    {"word": " Speaker", "start": 0.0, "end": 0.5},
                    {"word": " one", "start": 0.5, "end": 1.0},
                    {"word": " Speaker", "start": 3.0, "end": 3.5},  # 2000ms gap
                    {"word": " two", "start": 3.5, "end": 4.0},
                ],
            },
        ],
        "language": "es",
    }

    entries = transcribe_audio("/tmp/audio.wav", "mlx-community/whisper-medium-mlx")

    assert len(entries) == 2
    assert entries[0].text == "Speaker one"
    assert entries[1].text == "Speaker two"


@patch("pipeline.transcriber.mlx_whisper")
def test_transcribe_audio_skips_empty_segments(mock_mlx):
    mock_mlx.transcribe.return_value = {
        "text": "",
        "segments": [
            {
                "start": 1.0, "end": 2.0, "text": " Hola",
                "words": [{"word": " Hola", "start": 1.0, "end": 2.0}],
            },
            {"start": 3.0, "end": 4.0, "text": "   "},
            {"start": 5.0, "end": 6.0, "text": ""},
        ],
        "language": "es",
    }

    entries = transcribe_audio("/tmp/audio.wav", "mlx-community/whisper-medium-mlx")

    assert len(entries) == 1
    assert entries[0].text == "Hola"


@patch("pipeline.transcriber.mlx_whisper")
def test_transcribe_audio_passes_correct_parameters(mock_mlx):
    mock_mlx.transcribe.return_value = {
        "text": "",
        "segments": [],
        "language": "es",
    }

    transcribe_audio("/tmp/audio.wav", "mlx-community/whisper-medium-mlx")

    mock_mlx.transcribe.assert_called_once_with(
        "/tmp/audio.wav",
        path_or_hf_repo="mlx-community/whisper-medium-mlx",
        language="es",
        word_timestamps=True,
        condition_on_previous_text=True,
    )


# --- _ms_to_srt_timestamp ---


def test_ms_to_srt_timestamp_zero():
    assert _ms_to_srt_timestamp(0) == "00:00:00,000"


def test_ms_to_srt_timestamp_simple():
    assert _ms_to_srt_timestamp(1500) == "00:00:01,500"


def test_ms_to_srt_timestamp_full():
    # 1h 23m 45s 678ms
    ms = 1 * 3_600_000 + 23 * 60_000 + 45 * 1_000 + 678
    assert _ms_to_srt_timestamp(ms) == "01:23:45,678"


def test_ms_to_srt_timestamp_minutes_and_seconds():
    # 10m 5s 100ms
    ms = 10 * 60_000 + 5 * 1_000 + 100
    assert _ms_to_srt_timestamp(ms) == "00:10:05,100"


# --- segments_to_srt ---


def test_segments_to_srt_writes_correct_format(tmp_path):
    output_path = str(tmp_path / "output.srt")
    segments = [
        SubtitleEntry(start_ms=1500, end_ms=3200, text="Hola mundo"),
        SubtitleEntry(start_ms=5000, end_ms=7800, text="Adiós"),
    ]

    segments_to_srt(segments, output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    expected = (
        "1\n"
        "00:00:01,500 --> 00:00:03,200\n"
        "Hola mundo\n"
        "\n"
        "2\n"
        "00:00:05,000 --> 00:00:07,800\n"
        "Adiós\n"
        "\n"
    )
    assert content == expected


def test_segments_to_srt_empty_list_writes_empty_file(tmp_path):
    output_path = str(tmp_path / "output.srt")

    segments_to_srt([], output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert content == ""


def test_segments_to_srt_no_bom(tmp_path):
    output_path = str(tmp_path / "output.srt")
    segments = [SubtitleEntry(start_ms=0, end_ms=1000, text="Test")]

    segments_to_srt(segments, output_path)

    with open(output_path, "rb") as f:
        raw = f.read()

    # UTF-8 BOM is b'\xef\xbb\xbf'
    assert not raw.startswith(b"\xef\xbb\xbf")


def test_segments_to_srt_uses_utf8_encoding(tmp_path):
    output_path = str(tmp_path / "output.srt")
    segments = [
        SubtitleEntry(start_ms=0, end_ms=1000, text="¿Cómo estás?"),
    ]

    segments_to_srt(segments, output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "¿Cómo estás?" in content
