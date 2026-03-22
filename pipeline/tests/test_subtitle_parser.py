import os

from pipeline.subtitle_parser import SubtitleEntry, parse_srt


def test_parses_simple_srt(fixtures_dir):
    entries = parse_srt(os.path.join(fixtures_dir, "simple.srt"))

    assert len(entries) == 3
    assert entries[0] == SubtitleEntry(
        start_ms=1000, end_ms=3500, text="Hola, soy Homero Simpson."
    )
    assert entries[1] == SubtitleEntry(
        start_ms=5200, end_ms=7800, text="¡Ay, caramba!"
    )
    assert entries[2] == SubtitleEntry(
        start_ms=10000, end_ms=12500, text="No he sido yo."
    )


def test_joins_multiline_entries(fixtures_dir):
    entries = parse_srt(os.path.join(fixtures_dir, "multiline.srt"))

    assert len(entries) == 2
    assert entries[0].text == "Esta es una línea que continúa aquí."
    assert entries[1].text == "Y esta es otra línea con tres partes en el subtítulo."


def test_skips_malformed_entries(fixtures_dir):
    entries = parse_srt(os.path.join(fixtures_dir, "malformed.srt"))

    assert len(entries) == 3
    assert entries[0].text == "Línea válida."
    assert entries[1].text == "Otra línea válida."
    assert entries[2].text == "Última línea válida."


def test_returns_empty_for_empty_file(tmp_path):
    empty_file = tmp_path / "empty.srt"
    empty_file.write_text("")

    entries = parse_srt(str(empty_file))

    assert entries == []


def test_timestamp_parsing_precision(fixtures_dir):
    entries = parse_srt(os.path.join(fixtures_dir, "simple.srt"))

    assert entries[0].start_ms == 1000
    assert entries[0].end_ms == 3500
    assert entries[1].start_ms == 5200
    assert entries[1].end_ms == 7800
