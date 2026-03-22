from pipeline.subtitle_parser import SubtitleEntry
from pipeline.srt_cleaner import (
    clean_segment,
    remove_junk_segments,
    merge_short_segments,
    clean_srt,
)


# --- clean_segment ---


class TestCleanSegment:
    def test_strips_whitespace(self):
        assert clean_segment("  hello world  ") == "hello world"

    def test_normalizes_two_dots_to_ellipsis(self):
        assert clean_segment("wait..") == "wait..."

    def test_normalizes_four_dots_to_ellipsis(self):
        assert clean_segment("wait....") == "wait..."

    def test_normalizes_five_dots_to_ellipsis(self):
        assert clean_segment("hmm.....") == "hmm..."

    def test_preserves_three_dots(self):
        assert clean_segment("wait...") == "wait..."

    def test_preserves_single_dot(self):
        assert clean_segment("end.") == "end."

    def test_reduces_four_repetitions_to_three(self):
        assert clean_segment("no no no no") == "no, no, no"

    def test_reduces_five_repetitions_to_three(self):
        assert clean_segment("ja ja ja ja ja") == "ja, ja, ja"

    def test_keeps_three_repetitions(self):
        assert clean_segment("no no no") == "no, no, no"

    def test_does_not_reduce_two_repetitions(self):
        assert clean_segment("no no") == "no no"

    def test_preserves_original_case_in_repetitions(self):
        result = clean_segment("No no No no")
        assert result == "No, no, No"

    def test_combined_whitespace_and_ellipsis(self):
        assert clean_segment("  wait....  ") == "wait..."

    def test_empty_string(self):
        assert clean_segment("") == ""

    def test_multiple_ellipsis_occurrences(self):
        assert clean_segment("wait.. and then....") == "wait... and then..."


# --- remove_junk_segments ---


class TestRemoveJunkSegments:
    def _entry(self, text, start_ms=0, end_ms=1000):
        return SubtitleEntry(start_ms=start_ms, end_ms=end_ms, text=text)

    def test_removes_music_marker(self):
        segments = [self._entry("Hello"), self._entry("♪"), self._entry("World")]
        result = remove_junk_segments(segments)
        assert len(result) == 2
        assert result[0].text == "Hello"
        assert result[1].text == "World"

    def test_removes_musica_bracket(self):
        segments = [self._entry("[Música]"), self._entry("Hello")]
        result = remove_junk_segments(segments)
        assert len(result) == 1
        assert result[0].text == "Hello"

    def test_removes_music_bracket(self):
        segments = [self._entry("[Music]"), self._entry("Hello")]
        result = remove_junk_segments(segments)
        assert len(result) == 1

    def test_removes_aplausos_bracket(self):
        segments = [self._entry("[Aplausos]")]
        result = remove_junk_segments(segments)
        assert len(result) == 0

    def test_removes_risas_bracket(self):
        segments = [self._entry("[Risas]")]
        result = remove_junk_segments(segments)
        assert len(result) == 0

    def test_removes_single_character(self):
        segments = [self._entry("A"), self._entry("Hello")]
        result = remove_junk_segments(segments)
        assert len(result) == 1
        assert result[0].text == "Hello"

    def test_removes_segments_shorter_than_100ms(self):
        segments = [
            self._entry("Too short", start_ms=0, end_ms=50),
            self._entry("Normal", start_ms=100, end_ms=1000),
        ]
        result = remove_junk_segments(segments)
        assert len(result) == 1
        assert result[0].text == "Normal"

    def test_keeps_segments_exactly_100ms(self):
        segments = [self._entry("Borderline", start_ms=0, end_ms=100)]
        result = remove_junk_segments(segments)
        assert len(result) == 1

    def test_removes_hallucination_gracias_por_ver(self):
        segments = [self._entry("gracias por ver este video")]
        result = remove_junk_segments(segments)
        assert len(result) == 0

    def test_removes_hallucination_subtitulos_por(self):
        segments = [self._entry("subtítulos por la comunidad")]
        result = remove_junk_segments(segments)
        assert len(result) == 0

    def test_removes_hallucination_suscribete(self):
        segments = [self._entry("suscríbete al canal")]
        result = remove_junk_segments(segments)
        assert len(result) == 0

    def test_hallucination_case_insensitive(self):
        segments = [self._entry("GRACIAS POR VER")]
        result = remove_junk_segments(segments)
        assert len(result) == 0

    def test_removes_all_segments_in_run_of_three_identical(self):
        segments = [
            self._entry("Hello"),
            self._entry("repeat"),
            self._entry("repeat"),
            self._entry("repeat"),
            self._entry("World"),
        ]
        result = remove_junk_segments(segments)
        assert len(result) == 2
        assert result[0].text == "Hello"
        assert result[1].text == "World"

    def test_removes_all_segments_in_run_of_four_identical(self):
        segments = [
            self._entry("dup"),
            self._entry("dup"),
            self._entry("dup"),
            self._entry("dup"),
        ]
        result = remove_junk_segments(segments)
        assert len(result) == 0

    def test_keeps_two_identical_consecutive(self):
        segments = [self._entry("ok"), self._entry("ok")]
        result = remove_junk_segments(segments)
        assert len(result) == 2

    def test_preserves_normal_segments(self):
        segments = [
            self._entry("Hola mundo"),
            self._entry("Esto es una prueba"),
        ]
        result = remove_junk_segments(segments)
        assert len(result) == 2

    def test_returns_new_list(self):
        segments = [self._entry("Hello")]
        result = remove_junk_segments(segments)
        assert result is not segments


# --- merge_short_segments ---


class TestMergeShortSegments:
    def _entry(self, text, start_ms=0, end_ms=2000):
        return SubtitleEntry(start_ms=start_ms, end_ms=end_ms, text=text)

    def test_merges_short_segment_with_predecessor(self):
        segments = [
            self._entry("Hello world", start_ms=0, end_ms=2000),
            self._entry("ok", start_ms=2100, end_ms=2500),
        ]
        result = merge_short_segments(segments)
        assert len(result) == 1
        assert result[0].text == "Hello world ok"
        assert result[0].start_ms == 0
        assert result[0].end_ms == 2500

    def test_does_not_merge_if_gap_too_large(self):
        segments = [
            self._entry("Hello", start_ms=0, end_ms=2000),
            self._entry("ok", start_ms=3000, end_ms=3500),
        ]
        result = merge_short_segments(segments)
        assert len(result) == 2

    def test_does_not_merge_if_combined_text_exceeds_84_chars(self):
        long_text = "A" * 80
        segments = [
            self._entry(long_text, start_ms=0, end_ms=2000),
            self._entry("extra", start_ms=2100, end_ms=2500),
        ]
        result = merge_short_segments(segments)
        assert len(result) == 2

    def test_merges_when_combined_text_exactly_84_chars(self):
        text_a = "A" * 80
        text_b = "BBB"
        # "A"*80 + " " + "BBB" = 84
        segments = [
            self._entry(text_a, start_ms=0, end_ms=2000),
            self._entry(text_b, start_ms=2100, end_ms=2500),
        ]
        result = merge_short_segments(segments)
        assert len(result) == 1
        assert result[0].text == f"{text_a} {text_b}"

    def test_first_short_segment_stays_alone(self):
        segments = [
            self._entry("hi", start_ms=0, end_ms=500),
            self._entry("world sentence", start_ms=600, end_ms=3000),
        ]
        result = merge_short_segments(segments)
        assert len(result) == 2
        assert result[0].text == "hi"

    def test_does_not_merge_long_segments(self):
        segments = [
            self._entry("Hello world", start_ms=0, end_ms=2000),
            self._entry("Another long one", start_ms=2100, end_ms=4000),
        ]
        result = merge_short_segments(segments)
        assert len(result) == 2

    def test_custom_min_duration(self):
        segments = [
            self._entry("Hello", start_ms=0, end_ms=2000),
            self._entry("short", start_ms=2100, end_ms=3500),
        ]
        result = merge_short_segments(segments, min_duration_ms=2000)
        assert len(result) == 1

    def test_empty_list(self):
        result = merge_short_segments([])
        assert result == []

    def test_single_segment(self):
        segments = [self._entry("Hello", start_ms=0, end_ms=2000)]
        result = merge_short_segments(segments)
        assert len(result) == 1

    def test_returns_new_list(self):
        segments = [self._entry("Hello", start_ms=0, end_ms=2000)]
        result = merge_short_segments(segments)
        assert result is not segments

    def test_chain_merges_multiple_short_segments(self):
        segments = [
            self._entry("Base sentence", start_ms=0, end_ms=2000),
            self._entry("a", start_ms=2100, end_ms=2400),
            self._entry("b", start_ms=2450, end_ms=2700),
        ]
        result = merge_short_segments(segments)
        assert len(result) == 1
        assert result[0].text == "Base sentence a b"


# --- clean_srt ---


class TestCleanSrt:
    def _entry(self, text, start_ms=0, end_ms=2000):
        return SubtitleEntry(start_ms=start_ms, end_ms=end_ms, text=text)

    def test_full_pipeline_removes_junk_cleans_merges(self):
        segments = [
            self._entry("♪", start_ms=0, end_ms=2000),
            self._entry("  Hello world....  ", start_ms=3000, end_ms=5000),
            self._entry("ok", start_ms=5100, end_ms=5500),
        ]
        result = clean_srt(segments)
        assert len(result) == 1
        assert result[0].text == "Hello world... ok"

    def test_filters_empty_after_cleaning(self):
        segments = [self._entry("   ", start_ms=0, end_ms=2000)]
        result = clean_srt(segments)
        assert len(result) == 0

    def test_empty_input(self):
        assert clean_srt([]) == []

    def test_pipeline_order_junk_then_clean_then_merge(self):
        segments = [
            self._entry("gracias por ver", start_ms=0, end_ms=2000),
            self._entry("  Hola  ", start_ms=3000, end_ms=5000),
            self._entry("no no no no", start_ms=5100, end_ms=5500),
        ]
        result = clean_srt(segments)
        # "gracias por ver" removed by junk filter
        # "  Hola  " cleaned to "Hola"
        # "no no no no" cleaned to "no, no, no" and merged with Hola
        assert len(result) == 1
        assert result[0].text == "Hola no, no, no"
