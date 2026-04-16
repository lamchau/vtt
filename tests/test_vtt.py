#!/usr/bin/env python3
"""Tests for VTT to TXT converter"""

import os
from pathlib import Path

import pytest

from vtt import (
    analyze_speakers,
    convert_vtt_to_txt,
    count_words,
    extract_speakers,
    format_body,
    format_header,
    format_output_filename,
    get_vtt_duration_minutes,
    group_consecutive_messages,
    normalize_speaker,
    parse_vtt,
    parse_vtt_with_duration,
)

VTT_CONTENT = """\
WEBVTT

abc123-def456-ghi789/101-0
00:00:03.323 --> 00:00:06.915
<v Alice Johnson>Lorem ipsum dolor sit amet,
consectetur adipiscing elit.</v>

abc123-def456-ghi789/101-1
00:00:06.915 --> 00:00:11.832
<v Alice Johnson>Sed do eiusmod tempor incididunt
ut labore et dolore magna aliqua.</v>

abc123-def456-ghi789/68-0
00:00:13.083 --> 00:00:13.563
<v Bob Smith>Uh huh.</v>

abc123-def456-ghi789/70-0
00:00:13.843 --> 00:00:14.003
<v Bob Smith>Right.</v>

abc123-def456-ghi789/101-3
00:00:16.496 --> 00:00:19.963
<v Alice Johnson>Ut enim ad minim veniam,
quis nostrud exercitation.</v>
"""


@pytest.fixture
def sample_vtt_file(tmp_path: Path) -> Path:
    vtt_file = tmp_path / "test.vtt"
    vtt_file.write_text(VTT_CONTENT)
    os.utime(vtt_file, (1700000000, 1700000000))  # 2023-11-14
    return vtt_file


# --- normalize_speaker ---


def test_normalize_speaker_full_name() -> None:
    assert normalize_speaker("Alice Johnson") == "Alice Johnson"


def test_normalize_speaker_single_name() -> None:
    assert normalize_speaker("Rachana") == "Rachana MISSING_SURNAME"


def test_normalize_speaker_three_names() -> None:
    assert normalize_speaker("John van Doe") == "John van Doe"


def test_normalize_speaker_strips_whitespace() -> None:
    assert normalize_speaker("  Alice Johnson  ") == "Alice Johnson"


# --- parse_vtt ---


def test_parse_vtt_extracts_entries(sample_vtt_file: Path) -> None:
    entries = parse_vtt(str(sample_vtt_file))

    assert len(entries) == 5
    assert entries[0] == (
        "00:00:03",
        "Alice Johnson",
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    )
    assert entries[1] == (
        "00:00:06",
        "Alice Johnson",
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
    )
    assert entries[2] == ("00:00:13", "Bob Smith", "Uh huh.")
    assert entries[3] == ("00:00:13", "Bob Smith", "Right.")
    assert entries[4] == (
        "00:00:16",
        "Alice Johnson",
        "Ut enim ad minim veniam, quis nostrud exercitation.",
    )


def test_parse_vtt_handles_multiline_text(sample_vtt_file: Path) -> None:
    entries = parse_vtt(str(sample_vtt_file))

    assert "Lorem ipsum dolor sit amet, consectetur adipiscing elit." in entries[0][2]
    assert "\n" not in entries[0][2]


def test_parse_vtt_uses_full_name(sample_vtt_file: Path) -> None:
    entries = parse_vtt(str(sample_vtt_file))

    assert entries[0][1] == "Alice Johnson"
    assert entries[2][1] == "Bob Smith"


def test_parse_vtt_single_name_gets_no_surname(tmp_path: Path) -> None:
    vtt_content = """\
WEBVTT

00:00:03.323 --> 00:00:06.915
<v Rachana>Hello there.</v>
"""
    vtt_file = tmp_path / "single_name.vtt"
    vtt_file.write_text(vtt_content)

    entries = parse_vtt(str(vtt_file))

    assert entries[0][1] == "Rachana MISSING_SURNAME"


# --- group_consecutive_messages ---


def test_group_consecutive_messages_groups_by_speaker() -> None:
    entries = [
        ("00:00:03", "Alice Johnson", "Lorem ipsum dolor sit amet."),
        ("00:00:06", "Alice Johnson", "Consectetur adipiscing elit."),
        ("00:00:13", "Bob Smith", "Sed do eiusmod."),
        ("00:00:14", "Bob Smith", "Tempor incididunt."),
        ("00:00:16", "Alice Johnson", "Ut labore et dolore."),
    ]

    grouped = group_consecutive_messages(entries)

    assert len(grouped) == 3
    assert len(grouped[0]) == 2
    assert len(grouped[1]) == 2
    assert len(grouped[2]) == 1


def test_group_consecutive_messages_empty_list() -> None:
    grouped = group_consecutive_messages([])
    assert grouped == []


def test_group_consecutive_messages_single_entry() -> None:
    entries = [("00:00:03", "Alice Johnson", "Lorem ipsum.")]
    grouped = group_consecutive_messages(entries)

    assert len(grouped) == 1
    assert grouped[0] == entries


# --- extract_speakers ---


def test_extract_speakers_sorted() -> None:
    entries = [
        ("00:00:03", "Charlie Doe", "Hello."),
        ("00:00:06", "Alice Johnson", "Hi."),
        ("00:00:10", "Bob Smith", "Hey."),
    ]

    speakers = extract_speakers(entries)

    assert speakers == ["Alice Johnson", "Bob Smith", "Charlie Doe"]


def test_extract_speakers_empty() -> None:
    assert extract_speakers([]) == []


def test_extract_speakers_single() -> None:
    entries = [("00:00:03", "Alice Johnson", "Hello.")]

    assert extract_speakers(entries) == ["Alice Johnson"]


# --- format_body ---


def test_format_body_creates_correct_format() -> None:
    grouped = [
        [
            ("00:00:03", "Alice Johnson", "Lorem ipsum."),
            ("00:00:06", "Alice Johnson", "Dolor sit."),
        ],
        [("00:00:13", "Bob Smith", "Consectetur.")],
    ]

    output = format_body(grouped)
    lines = output.split("\n")

    assert lines[0] == "[00:00:03] Alice Johnson: Lorem ipsum."
    assert lines[1] == "[00:00:06] Alice Johnson: Dolor sit."
    assert lines[2] == "[00:00:13] Bob Smith: Consectetur."


def test_format_body_no_blank_lines() -> None:
    grouped = [
        [("00:00:03", "Alice Johnson", "Lorem ipsum.")],
        [("00:00:13", "Bob Smith", "Dolor sit.")],
    ]

    output = format_body(grouped)

    assert "\n\n" not in output


# --- get_vtt_duration_minutes ---


def test_get_vtt_duration_minutes_short(sample_vtt_file: Path) -> None:
    duration = get_vtt_duration_minutes(sample_vtt_file)
    assert duration == 1


def test_get_vtt_duration_minutes_long(tmp_path: Path) -> None:
    vtt_content = """\
WEBVTT

00:00:03.323 --> 00:00:06.915
<v Alice Johnson>Start.</v>

00:55:30.000 --> 00:55:35.000
<v Alice Johnson>Near the end.</v>
"""
    vtt_file = tmp_path / "long.vtt"
    vtt_file.write_text(vtt_content)

    duration = get_vtt_duration_minutes(vtt_file)
    assert duration == 56


# --- format_output_filename ---


def test_format_output_filename_uses_date_and_stem(sample_vtt_file: Path) -> None:
    filename = format_output_filename(sample_vtt_file)
    assert filename == "2023-11-14__test.txt"


def test_format_output_filename_lowercases_and_underscores(tmp_path: Path) -> None:
    vtt_file = tmp_path / "[HOLD] Eval Roundtable.vtt"
    vtt_file.write_text("WEBVTT\n")
    os.utime(vtt_file, (1700000000, 1700000000))

    filename = format_output_filename(vtt_file)
    assert filename == "2023-11-14__[hold]-eval-roundtable.txt"


# --- format_header ---


def test_format_header_contains_metadata(sample_vtt_file: Path) -> None:
    entries = parse_vtt(str(sample_vtt_file))
    header = format_header(sample_vtt_file, entries)

    assert "# date: 2023-11-14" in header
    assert "# duration: 1 min" in header
    assert "# speakers:" in header
    assert "#   - Alice Johnson" in header
    assert "#   - Bob Smith" in header
    assert "# source: test.vtt" in header


# --- end to end ---


def test_end_to_end_conversion(sample_vtt_file: Path) -> None:
    output_path = str(sample_vtt_file.parent / "output.txt")
    convert_vtt_to_txt(str(sample_vtt_file), output_path)

    output = Path(output_path).read_text()

    # header present
    assert output.startswith("# date: 2023-11-14")
    assert "# speakers:" in output
    assert "#   - Alice Johnson" in output
    assert "#   - Bob Smith" in output

    # body present after blank line
    body_lines = output.split("\n\n", maxsplit=1)[1].strip().split("\n")
    assert len(body_lines) == 5
    assert body_lines[0].startswith("[00:00:03] Alice Johnson:")
    assert body_lines[2].startswith("[00:00:13] Bob Smith:")


def test_end_to_end_default_filename(sample_vtt_file: Path) -> None:
    # run from the vtt file's directory so default output lands there
    original_dir = Path.cwd()
    os.chdir(sample_vtt_file.parent)
    try:
        convert_vtt_to_txt(str(sample_vtt_file))
        expected = sample_vtt_file.parent / "2023-11-14__test.txt"
        assert expected.exists()
    finally:
        os.chdir(original_dir)


# --- count_words ---


def test_count_words_english() -> None:
    assert count_words("Hello world foo bar") == 4


def test_count_words_cjk_chinese() -> None:
    # each CJK character counts as one word
    assert count_words("今天的会议很重要") == 8


def test_count_words_cjk_japanese() -> None:
    assert count_words("こんにちは") == 5


def test_count_words_mixed_cjk_and_english() -> None:
    # "hello" = 1 word, 3 CJK chars = 3 words, "world" = 1 word
    assert count_words("hello 今天好 world") == 5


def test_count_words_empty() -> None:
    assert count_words("") == 0


def test_count_words_whitespace_only() -> None:
    assert count_words("   ") == 0


# --- parse_vtt_with_duration ---


def test_parse_vtt_with_duration_entry_count(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    assert len(entries) == 5


def test_parse_vtt_with_duration_calculates_duration(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    # 00:00:03.323 --> 00:00:06.915
    assert entries[0][2] == pytest.approx(3.592, abs=0.001)
    # 00:00:06.915 --> 00:00:11.832
    assert entries[1][2] == pytest.approx(4.917, abs=0.001)
    # 00:00:13.083 --> 00:00:13.563
    assert entries[2][2] == pytest.approx(0.480, abs=0.001)
    # 00:00:13.843 --> 00:00:14.003
    assert entries[3][2] == pytest.approx(0.160, abs=0.001)
    # 00:00:16.496 --> 00:00:19.963
    assert entries[4][2] == pytest.approx(3.467, abs=0.001)


def test_parse_vtt_with_duration_speaker_names(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    assert entries[0][1] == "Alice Johnson"
    assert entries[2][1] == "Bob Smith"


def test_parse_vtt_with_duration_text_content(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    assert entries[0][3] == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    assert entries[2][3] == "Uh huh."


# --- analyze_speakers ---


def test_analyze_speakers_contains_all_speakers(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file)
    assert "Alice Johnson" in output
    assert "Bob Smith" in output


def test_analyze_speakers_correct_word_count(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file)
    lines = output.split("\n")
    alice_line = next(line for line in lines if "Alice Johnson" in line)
    bob_line = next(line for line in lines if "Bob Smith" in line)
    # alice: 8 + 11 + 8 = 27 words
    # bob: 2 + 1 = 3 words
    assert "27" in alice_line
    assert "3" in bob_line


def test_analyze_speakers_shows_total(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file)
    assert "Total" in output


def test_analyze_speakers_shows_duration_header(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file)
    assert "duration:" in output


def test_analyze_speakers_shows_wpm_column(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file)
    assert "WPM" in output


def test_analyze_speakers_shows_percentage_column(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file)
    # header has % column
    assert "%" in output
    # total row shows 100%
    lines = output.split("\n")
    total_line = next(line for line in lines if "Total" in line)
    assert "100%" in total_line
    # individual speaker percentages add up (approximately)
    data_lines = [
        line
        for line in lines
        if line.strip()
        and "─" not in line
        and not line.startswith("#")
        and "Speaker" not in line
        and "Total" not in line
    ]
    # each data line should have a percentage value
    for data_line in data_lines:
        assert "%" in data_line


def test_analyze_speakers_sort_by_words(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file, sort_by="words")
    lines = output.split("\n")
    # find data rows (between separators)
    data_lines = [
        line
        for line in lines
        if line.strip()
        and "─" not in line
        and not line.startswith("#")
        and "Speaker" not in line
        and "Total" not in line
    ]
    # alice has more words, should come first when sorted by words descending
    assert "Alice Johnson" in data_lines[0]


def test_analyze_speakers_sort_by_duration(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file, sort_by="duration")
    lines = output.split("\n")
    data_lines = [
        line
        for line in lines
        if line.strip()
        and "─" not in line
        and not line.startswith("#")
        and "Speaker" not in line
        and "Total" not in line
    ]
    # alice has more duration, should come first
    assert "Alice Johnson" in data_lines[0]


def test_analyze_speakers_sort_by_speaker(sample_vtt_file: Path) -> None:
    entries = parse_vtt_with_duration(str(sample_vtt_file))
    output = analyze_speakers(entries, sample_vtt_file, sort_by="speaker")
    lines = output.split("\n")
    data_lines = [
        line
        for line in lines
        if line.strip()
        and "─" not in line
        and not line.startswith("#")
        and "Speaker" not in line
        and "Total" not in line
    ]
    # alphabetical: Alice before Bob
    assert "Alice Johnson" in data_lines[0]
    assert "Bob Smith" in data_lines[1]


def test_analyze_speakers_empty_entries(sample_vtt_file: Path) -> None:
    output = analyze_speakers([], sample_vtt_file)
    # should handle gracefully — at minimum not crash
    assert "0" in output or "Total" in output or "no entries" in output.lower()
