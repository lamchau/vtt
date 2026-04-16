#!/usr/bin/env python3
"""VTT file toolkit - convert and analyze WebVTT files."""

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

type Entry = tuple[str, str, str]
type GroupedEntries = list[list[Entry]]


def normalize_speaker(name: str) -> str:
    """Normalize speaker name: verbatim full name, MISSING_SURNAME if single word."""
    name = name.strip()
    parts = name.split()
    if len(parts) == 1:
        return f"{parts[0]} MISSING_SURNAME"
    return name


def parse_vtt(vtt_path: str) -> list[Entry]:
    """Parse VTT file into list of (timestamp, speaker, text) entries."""
    entries: list[Entry] = []
    with open(vtt_path, encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if "-->" in line and (timestamp_match := re.match(r"(\d{2}:\d{2}:\d{2})", line)):
            timestamp = timestamp_match.group(1)

            i += 1
            content_lines: list[str] = []
            while i < len(lines):
                content_line = lines[i]
                if "</v>" in content_line or not content_line.strip():
                    content_lines.append(content_line)
                    break
                content_lines.append(content_line)
                i += 1

            full_content = "".join(content_lines)

            if speaker_match := re.match(r"<v ([^>]+)>(.*)</v>", full_content, re.DOTALL):
                raw_name = speaker_match.group(1)
                speaker = normalize_speaker(raw_name)
                text = speaker_match.group(2).strip()
                text = " ".join(text.split())
                entries.append((timestamp, speaker, text))

        i += 1

    return entries


def group_consecutive_messages(entries: list[Entry]) -> GroupedEntries:
    """Group consecutive entries from the same speaker."""
    if not entries:
        return []

    grouped: GroupedEntries = []
    current_group = [entries[0]]

    for entry in entries[1:]:
        _, speaker, _ = entry
        _, prev_speaker, _ = current_group[-1]

        if speaker == prev_speaker:
            current_group.append(entry)
        else:
            grouped.append(current_group)
            current_group = [entry]

    grouped.append(current_group)
    return grouped


def get_vtt_duration_minutes(vtt_path: Path) -> int:
    """Calculate duration in minutes from VTT timestamps."""
    with open(vtt_path, encoding="utf-8") as f:
        content = f.read()

    timestamps = re.findall(r"(\d{2}):(\d{2}):(\d{2})\.\d+ -->", content)
    if not timestamps:
        return 0

    hours, minutes, seconds = map(int, timestamps[-1])
    total_minutes = hours * 60 + minutes + (1 if seconds > 0 else 0)

    return total_minutes


def extract_speakers(entries: list[Entry]) -> list[str]:
    """Extract unique speakers, sorted alphabetically."""
    speakers: set[str] = set()
    for _, speaker, _ in entries:
        speakers.add(speaker)
    return sorted(speakers)


def format_header(vtt_path: Path, entries: list[Entry]) -> str:
    """Format metadata header block."""
    mtime = vtt_path.stat().st_mtime
    date_str = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d")
    duration = get_vtt_duration_minutes(vtt_path)
    speakers = extract_speakers(entries)
    source = vtt_path.name

    speaker_lines = "\n".join(f"#   - {s}" for s in speakers)
    header_lines = [
        f"# date: {date_str}",
        f"# duration: {duration} min",
        f"# speakers:\n{speaker_lines}",
        f"# source: {source}",
    ]
    return "\n".join(header_lines)


def format_body(grouped_entries: GroupedEntries) -> str:
    """Format entries as IRC-style timestamped lines."""
    lines: list[str] = []
    for group in grouped_entries:
        for timestamp, speaker, text in group:
            lines.append(f"[{timestamp}] {speaker}: {text}")
    return "\n".join(lines)


def format_output_filename(vtt_path: Path) -> str:
    """Generate default output filename: YYYY-MM-DD__original_stem.txt"""
    mtime = vtt_path.stat().st_mtime
    date_str = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d")
    stem = vtt_path.stem.lower().replace(" ", "-")
    return f"{date_str}__{stem}.txt"


def convert_vtt_to_txt(vtt_path: str, output_path: str | None = None) -> None:
    """Convert a VTT file to IRC-style timestamped text."""
    vtt_file = Path(vtt_path)

    if not vtt_file.exists():
        print(f"[error] file '{vtt_path}' not found", file=sys.stderr)
        sys.exit(1)

    entries = parse_vtt(str(vtt_file))

    if not entries:
        print(f"[error] no entries found in '{vtt_path}'", file=sys.stderr)
        sys.exit(1)

    if output_path is None:
        output_filename = format_output_filename(vtt_file)
        output_path = output_filename

    grouped = group_consecutive_messages(entries)
    header = format_header(vtt_file, entries)
    body = format_body(grouped)
    output_text = f"{header}\n\n{body}\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"{output_path}")


def main() -> None:
    """CLI entry point with subcommands."""
    parser = argparse.ArgumentParser(
        prog="vtt",
        description="VTT file toolkit - convert and analyze WebVTT files",
    )
    subparsers = parser.add_subparsers(dest="command")

    # convert subcommand
    convert_parser = subparsers.add_parser(
        "convert",
        help="convert VTT to plain text",
    )
    convert_parser.add_argument("vtt_file", help="path to VTT file")
    convert_parser.add_argument("--output", "-o", help="output file path")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "convert":
        convert_vtt_to_txt(args.vtt_file, args.output)


if __name__ == "__main__":
    main()
