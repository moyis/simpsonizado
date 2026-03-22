import os
from unittest.mock import MagicMock, call, patch

import pytest

from pipeline.frame_extractor import (
    FRAME_RATE_DIVISOR,
    _compute_subtitle_frame_ranges,
    _merge_ranges,
    compute_extraction_fps,
    detect_fps,
    extract_frames_and_thumbnails,
    extract_frames_for_subtitles,
    find_spanish_subtitle_track,
    extract_subtitles,
    remove_unsubtitled_frames,
)
from pipeline.subtitle_parser import SubtitleEntry


@patch("pipeline.frame_extractor.subprocess.run")
def test_detect_fps_parses_fraction(mock_run):
    mock_run.return_value = MagicMock(
        stdout="24000/1001\n", returncode=0
    )

    fps = detect_fps("/path/to/episode.mkv")

    assert abs(fps - 23.976) < 0.001
    mock_run.assert_called_once()


@patch("pipeline.frame_extractor.subprocess.run")
def test_detect_fps_parses_integer(mock_run):
    mock_run.return_value = MagicMock(stdout="24/1\n", returncode=0)

    fps = detect_fps("/path/to/episode.mkv")

    assert fps == 24.0


@patch("pipeline.frame_extractor.subprocess.run")
def test_detect_fps_raises_on_failure(mock_run):
    mock_run.return_value = MagicMock(stdout="", returncode=1, stderr="error")

    with pytest.raises(RuntimeError, match="detect FPS"):
        detect_fps("/path/to/episode.mkv")


@patch("pipeline.frame_extractor.subprocess.run")
def test_find_spanish_subtitle_track(mock_run):
    ffprobe_output = (
        '{"streams":[{"index":2,"codec_type":"subtitle","tags":{"language":"spa"}},'
        '{"index":3,"codec_type":"subtitle","tags":{"language":"eng"}}]}'
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_subtitle_track("/path/to/episode.mkv")

    assert track == 0  # first subtitle stream = 0:s:0


@patch("pipeline.frame_extractor.subprocess.run")
def test_find_spanish_track_skips_forced_forzado(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":2,"codec_type":"subtitle","tags":{"language":"spa","title":"Español Forzado"}},'
        '{"index":3,"codec_type":"subtitle","tags":{"language":"spa","title":"Español"}},'
        '{"index":4,"codec_type":"subtitle","tags":{"language":"eng","title":"English"}}'
        ']}'
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_subtitle_track("/path/to/episode.mkv")

    assert track == 1  # skips stream 0 (Forzado), picks stream 1


@patch("pipeline.frame_extractor.subprocess.run")
def test_find_spanish_track_skips_forced_english(mock_run):
    ffprobe_output = (
        '{"streams":['
        '{"index":2,"codec_type":"subtitle","tags":{"language":"spa","title":"Forced"}},'
        '{"index":3,"codec_type":"subtitle","tags":{"language":"spa","title":"Spanish"}}'
        ']}'
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_subtitle_track("/path/to/episode.mkv")

    assert track == 1


@patch("pipeline.frame_extractor.subprocess.run")
def test_find_spanish_track_returns_none_when_missing(mock_run):
    ffprobe_output = (
        '{"streams":[{"index":3,"codec_type":"subtitle","tags":{"language":"eng"}}]}'
    )
    mock_run.return_value = MagicMock(stdout=ffprobe_output, returncode=0)

    track = find_spanish_subtitle_track("/path/to/episode.mkv")

    assert track is None


@patch("pipeline.frame_extractor.subprocess.run")
def test_extract_subtitles_calls_ffmpeg(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    output_path = extract_subtitles("/path/to/episode.mkv", sub_track=0, output_dir="/tmp")

    assert output_path.endswith(".srt")
    args = mock_run.call_args[0][0]
    assert "ffmpeg" in args[0]
    assert "-map" in args
    assert "0:s:0" in args


@patch("pipeline.frame_extractor.subprocess.run")
def test_extract_frames_calls_ffmpeg_with_split_filter(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    extract_frames_and_thumbnails(
        input_path="/path/to/episode.mkv",
        output_dir="/tmp/frames/S01E01",
        fps=23.976,
    )

    args = mock_run.call_args[0][0]
    cmd_str = " ".join(args)
    assert "libwebp" in cmd_str
    # Verify reduced fps is used (native / FRAME_RATE_DIVISOR)
    expected_fps = 23.976 / FRAME_RATE_DIVISOR
    assert f"fps={expected_fps}" in cmd_str


def test_compute_extraction_fps():
    assert compute_extraction_fps(24.0) == 24.0 / FRAME_RATE_DIVISOR
    assert abs(compute_extraction_fps(23.976) - 23.976 / 7) < 0.001


@patch("pipeline.frame_extractor.subprocess.run")
def test_extract_frames_raises_on_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="encoding error")

    with pytest.raises(RuntimeError, match="extract frames"):
        extract_frames_and_thumbnails("/path/to/ep.mkv", "/tmp/frames", 24.0)


def _create_frames(directory, count):
    """Create numbered frame files in directory."""
    os.makedirs(directory, exist_ok=True)
    for i in range(1, count + 1):
        with open(os.path.join(directory, f"frame_{i:06d}.webp"), "w") as f:
            f.write("")


def test_unsubtitled_frames_are_removed(tmp_path):
    frames_dir = str(tmp_path / "frames")
    _create_frames(frames_dir, 10)

    # Subtitle covers frames 3-5 (at 1 fps: 2s-5s → frames 3,4,5)
    entries = [SubtitleEntry(start_ms=2000, end_ms=4999, text="Hola")]
    extraction_fps = 1.0

    removed = remove_unsubtitled_frames(frames_dir, entries, extraction_fps)

    remaining = sorted(os.listdir(frames_dir))
    assert remaining == ["frame_000003.webp", "frame_000004.webp", "frame_000005.webp"]
    assert removed == 7


def test_no_frames_removed_when_all_have_subtitles(tmp_path):
    frames_dir = str(tmp_path / "frames")
    _create_frames(frames_dir, 3)

    # Subtitle covers entire range
    entries = [SubtitleEntry(start_ms=0, end_ms=3000, text="Todo")]
    extraction_fps = 1.0

    removed = remove_unsubtitled_frames(frames_dir, entries, extraction_fps)

    remaining = sorted(os.listdir(frames_dir))
    assert len(remaining) == 3
    assert removed == 0


def test_multiple_subtitles_keep_union_of_frames(tmp_path):
    frames_dir = str(tmp_path / "frames")
    _create_frames(frames_dir, 10)

    entries = [
        SubtitleEntry(start_ms=0, end_ms=1999, text="Primero"),   # frames 1,2
        SubtitleEntry(start_ms=7000, end_ms=8999, text="Segundo"),  # frames 8,9
    ]
    extraction_fps = 1.0

    removed = remove_unsubtitled_frames(frames_dir, entries, extraction_fps)

    remaining = sorted(os.listdir(frames_dir))
    assert remaining == [
        "frame_000001.webp", "frame_000002.webp",
        "frame_000008.webp", "frame_000009.webp",
    ]
    assert removed == 6


def test_all_frames_removed_when_no_subtitles(tmp_path):
    frames_dir = str(tmp_path / "frames")
    _create_frames(frames_dir, 5)

    removed = remove_unsubtitled_frames(frames_dir, [], 1.0)

    remaining = [f for f in os.listdir(frames_dir) if f.startswith("frame_")]
    assert remaining == []
    assert removed == 5


# --- _merge_ranges tests ---


def test_merge_ranges_empty():
    assert _merge_ranges([]) == []


def test_merge_ranges_no_overlap():
    assert _merge_ranges([(0, 2), (5, 7), (10, 12)]) == [
        (0, 2), (5, 7), (10, 12)
    ]


def test_merge_ranges_adjacent():
    # Adjacent ranges (gap=0 default) are merged
    assert _merge_ranges([(0, 2), (3, 5)]) == [(0, 5)]


def test_merge_ranges_overlapping():
    assert _merge_ranges([(0, 5), (3, 8)]) == [(0, 8)]


def test_merge_ranges_with_gap():
    # Ranges within gap of each other are merged
    assert _merge_ranges([(0, 2), (4, 6)], gap=1) == [(0, 6)]
    assert _merge_ranges([(0, 2), (5, 7)], gap=1) == [(0, 2), (5, 7)]


def test_merge_ranges_unsorted_input():
    assert _merge_ranges([(10, 12), (0, 2), (5, 7)]) == [
        (0, 2), (5, 7), (10, 12)
    ]


# --- _compute_subtitle_frame_ranges tests ---


def test_compute_subtitle_frame_ranges_single_entry():
    entries = [SubtitleEntry(start_ms=2000, end_ms=5000, text="Hola")]
    ranges = _compute_subtitle_frame_ranges(entries, extraction_fps=1.0)
    # n_start = floor(2.0 * 1.0) = 2, n_end = floor(5.0 * 1.0) = 5
    assert ranges == [(2, 5)]


def test_compute_subtitle_frame_ranges_merges_close_entries():
    entries = [
        SubtitleEntry(start_ms=0, end_ms=2000, text="A"),
        SubtitleEntry(start_ms=2500, end_ms=4000, text="B"),
    ]
    ranges = _compute_subtitle_frame_ranges(entries, extraction_fps=1.0)
    # Entry A: n_start=0, n_end=2. Entry B: n_start=2, n_end=4.
    # gap between 2 and 2 is 0, within merge gap of 1, so merged
    assert ranges == [(0, 4)]


def test_compute_subtitle_frame_ranges_keeps_distant_entries():
    entries = [
        SubtitleEntry(start_ms=0, end_ms=1000, text="A"),
        SubtitleEntry(start_ms=5000, end_ms=6000, text="B"),
    ]
    ranges = _compute_subtitle_frame_ranges(entries, extraction_fps=1.0)
    # Entry A: (0, 1). Entry B: (5, 6). Gap = 5-1-1=3, not adjacent.
    assert ranges == [(0, 1), (5, 6)]


# --- extract_frames_for_subtitles tests ---


@patch("pipeline.frame_extractor.multiprocessing.Pool")
@patch("pipeline.frame_extractor.subprocess.run")
def test_extract_for_subtitles_uses_seek_and_jpeg(mock_run, mock_pool, tmp_path):
    output_dir = str(tmp_path / "frames")
    mock_run.return_value = MagicMock(returncode=0)
    mock_pool.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_pool.return_value.__exit__ = MagicMock(return_value=False)

    entries = [
        SubtitleEntry(start_ms=0, end_ms=2000, text="A"),
        SubtitleEntry(start_ms=5000, end_ms=7000, text="B"),
    ]

    extract_frames_for_subtitles("/path/to/ep.mkv", output_dir, 7.0, entries)

    # Should have called ffmpeg with -ss seeking and JPEG output
    assert mock_run.call_count >= 1
    args = mock_run.call_args[0][0]
    cmd_str = " ".join(str(a) for a in args)
    assert "-ss" in cmd_str
    assert ".jpg" in cmd_str
    assert "-map" in cmd_str


@patch("pipeline.frame_extractor.subprocess.run")
def test_extract_for_subtitles_returns_zero_for_empty_entries(mock_run, tmp_path):
    output_dir = str(tmp_path / "frames")
    count = extract_frames_for_subtitles("/path/to/ep.mkv", output_dir, 24.0, [])
    assert count == 0
    mock_run.assert_not_called()


@patch("pipeline.frame_extractor.multiprocessing.Pool")
@patch("pipeline.frame_extractor.subprocess.run")
def test_extract_for_subtitles_raises_on_failure(mock_run, mock_pool, tmp_path):
    output_dir = str(tmp_path / "frames")
    mock_run.return_value = MagicMock(returncode=1, stderr="encoding error")

    entries = [SubtitleEntry(start_ms=0, end_ms=2000, text="A")]

    with pytest.raises(RuntimeError, match="extract frames"):
        extract_frames_for_subtitles("/path/to/ep.mkv", output_dir, 7.0, entries)


@patch("pipeline.frame_extractor.multiprocessing")
@patch("pipeline.frame_extractor.subprocess.run")
def test_extract_for_subtitles_converts_jpeg_to_webp(mock_run, mock_mp, tmp_path):
    """Verify two-step pipeline: JPEG extraction + parallel WebP conversion."""
    output_dir = str(tmp_path / "frames")

    # Subtitle covers 0-based frames 2..4 at extraction_fps=1fps (native=7fps/7)
    entries = [SubtitleEntry(start_ms=2000, end_ms=4000, text="Hola")]

    def fake_ffmpeg(cmd, **kwargs):
        # Create fake JPEG files in the temp dir
        jpeg_pattern = cmd[-1]  # last arg is the output pattern
        jpeg_dir = os.path.dirname(jpeg_pattern)
        os.makedirs(jpeg_dir, exist_ok=True)
        # -start_number determines first frame number
        start_num_idx = cmd.index("-start_number") + 1
        start_num = int(cmd[start_num_idx])
        for i in range(3):  # 3 frames
            with open(
                os.path.join(jpeg_dir, f"frame_{start_num + i:06d}.jpg"), "w"
            ) as f:
                f.write(f"jpeg_{i}")
        return MagicMock(returncode=0)

    mock_run.side_effect = fake_ffmpeg

    # Mock cwebp conversion: actually create the WebP files
    def fake_pool_map(func, args_list):
        for src, dst, quality in args_list:
            with open(dst, "w") as f:
                f.write("webp")

    mock_mp.cpu_count.return_value = 4
    pool_instance = MagicMock()
    pool_instance.map.side_effect = fake_pool_map
    mock_mp.Pool.return_value.__enter__ = MagicMock(return_value=pool_instance)
    mock_mp.Pool.return_value.__exit__ = MagicMock(return_value=False)

    count = extract_frames_for_subtitles("/path/to/ep.mkv", output_dir, 7.0, entries)

    assert count == 3
    remaining = sorted(os.listdir(output_dir))
    assert all(f.endswith(".webp") for f in remaining)

    # Verify pool.map was called with conversion args
    pool_instance.map.assert_called_once()
    convert_args = pool_instance.map.call_args[0][1]
    assert len(convert_args) == 3
    # Each arg is (src_jpg, dst_webp, quality)
    for src, dst, quality in convert_args:
        assert src.endswith(".jpg")
        assert dst.endswith(".webp")
        assert quality == 25
