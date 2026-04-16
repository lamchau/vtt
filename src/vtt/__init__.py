#!/usr/bin/env python3
"""VTT file toolkit - convert and analyze WebVTT files."""

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

type Entry = tuple[str, str, str]
type GroupedEntries = list[list[Entry]]
type TimedEntry = tuple[str, str, float, str]  # (timestamp, speaker, duration_seconds, text)

DEFAULT_BASE_URL = "http://localhost:4000/v1"


def fetch_models(base_url: str = DEFAULT_BASE_URL) -> list[str]:
    """Fetch available model names from an OpenAI-compatible API. Returns empty list on failure."""
    try:
        request = urllib.request.Request(f"{base_url}/models")
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        # filter out wildcard aliases (e.g. "sonnet*") — keep clean names only
        models = [m["id"] for m in data.get("data", []) if not m["id"].endswith("*")]
        return sorted(models)
    except urllib.error.URLError, TimeoutError, KeyError:
        return []


SUMMARY_SYSTEM_PROMPT = """\
You are a meeting summarizer. Given a transcript, produce a concise summary with:

1. Overview: 1-2 sentence summary of the meeting topic and outcome
2. Key Points: Bulleted list of main discussion points
3. Action Items: Any tasks, decisions, or follow-ups mentioned
4. Participants: Brief note on each speaker's role/contribution

Keep it concise. Use plain text, no markdown headers. Bullet points with dashes.\
"""

PLAN_SYSTEM_PROMPT = """\
You are a meeting analyst focused on extracting actionable outcomes. Given a transcript, produce:

1. Decisions: What was decided, by whom
2. Action Items: Each with owner, deadline if mentioned, and description
3. Open Questions: Unresolved items that need follow-up
4. Next Steps: What happens next, any scheduled follow-ups

Keep it concise. Use plain text, no markdown headers. Bullet points with dashes.\
"""


def normalize_speaker(name: str) -> str:
    """Normalize speaker name: verbatim full name, MISSING_SURNAME if single word."""
    name = name.strip()
    parts = name.split()
    if len(parts) == 1:
        return f"{parts[0]} MISSING_SURNAME"
    return name


def _is_cjk(char: str) -> bool:
    """Check if a character is CJK (Chinese, Japanese, Korean)."""
    category = unicodedata.category(char)
    # Lo = "Letter, other" covers CJK ideographs; also check common CJK ranges
    if category == "Lo":
        codepoint = ord(char)
        # CJK unified ideographs + extensions, kana, hangul, etc.
        is_cjk_range = (
            0x4E00 <= codepoint <= 0x9FFF  # CJK unified ideographs
            or 0x3400 <= codepoint <= 0x4DBF  # CJK extension A
            or 0x3040 <= codepoint <= 0x309F  # hiragana
            or 0x30A0 <= codepoint <= 0x30FF  # katakana
            or 0xAC00 <= codepoint <= 0xD7AF  # hangul syllables
            or 0x20000 <= codepoint <= 0x2A6DF  # CJK extension B
        )
        return is_cjk_range
    return False


def count_words(text: str) -> int:
    """Count words with CJK awareness.

    Each CJK character counts as one word. Non-CJK text is split
    on whitespace. Mixed text handles both correctly.
    """
    word_count = 0
    current_token = ""

    for char in text:
        if _is_cjk(char):
            # flush any accumulated non-CJK token
            if current_token.strip():
                word_count += len(current_token.split())
            current_token = ""
            # each CJK character counts as one word
            word_count += 1
        else:
            current_token += char

    # flush remaining non-CJK token
    if current_token.strip():
        word_count += len(current_token.split())

    return word_count


def _parse_timestamp_seconds(timestamp_str: str) -> float:
    """Parse a VTT timestamp like '00:00:03.323' into total seconds."""
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})\.(\d+)", timestamp_str)
    if not match:
        return 0.0
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    milliseconds = int(match.group(4))
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


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


def parse_vtt_with_duration(vtt_path: str) -> list[TimedEntry]:
    """Parse VTT file into list of (timestamp, speaker, duration_seconds, text) entries."""
    timed_entries: list[TimedEntry] = []
    with open(vtt_path, encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # match the timestamp line: "00:00:03.323 --> 00:00:06.915"
        arrow_match = re.match(
            r"(\d{2}:\d{2}:\d{2}\.\d+)\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d+)",
            line,
        )
        if arrow_match:
            start_full = arrow_match.group(1)
            end_full = arrow_match.group(2)
            # truncate to HH:MM:SS for display timestamp
            timestamp = start_full[:8]
            start_seconds = _parse_timestamp_seconds(start_full)
            end_seconds = _parse_timestamp_seconds(end_full)
            duration_seconds = end_seconds - start_seconds

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
                timed_entries.append((timestamp, speaker, duration_seconds, text))

        i += 1

    return timed_entries


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


def format_summary_filename(vtt_path: Path) -> str:
    """Generate default summary filename: YYYY-MM-DD__original_stem.summary.txt"""
    mtime = vtt_path.stat().st_mtime
    date_str = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d")
    stem = vtt_path.stem.lower().replace(" ", "-")
    return f"{date_str}__{stem}.summary.txt"


def analyze_speakers(
    entries: list[TimedEntry],
    vtt_path: Path,
    sort_by: str = "speaker",
) -> str:
    """Produce a formatted speaker analysis table from timed entries."""
    duration_minutes = get_vtt_duration_minutes(vtt_path)
    source_name = vtt_path.name

    # collect per-speaker stats
    speaker_order: list[str] = []
    speaker_word_counts: dict[str, int] = {}
    speaker_durations: dict[str, float] = {}

    for _, speaker, duration_seconds, text in entries:
        if speaker not in speaker_word_counts:
            speaker_order.append(speaker)
            speaker_word_counts[speaker] = 0
            speaker_durations[speaker] = 0.0

        speaker_word_counts[speaker] += count_words(text)
        speaker_durations[speaker] += duration_seconds

    total_words = sum(speaker_word_counts.values())
    total_duration_seconds = sum(speaker_durations.values())

    # compute wpm and percentage for each speaker
    speaker_wpm: dict[str, int] = {}
    speaker_pct: dict[str, int] = {}
    for speaker in speaker_order:
        duration_min = speaker_durations[speaker] / 60
        if duration_min > 0:
            speaker_wpm[speaker] = round(speaker_word_counts[speaker] / duration_min)
        else:
            speaker_wpm[speaker] = 0

        if total_duration_seconds > 0:
            speaker_pct[speaker] = round(speaker_durations[speaker] / total_duration_seconds * 100)
        else:
            speaker_pct[speaker] = 0

    if total_duration_seconds > 0:
        total_wpm = round(total_words / (total_duration_seconds / 60))
    else:
        total_wpm = 0

    # sort speakers by requested column (descending for numeric, ascending for name)
    if sort_by == "duration":
        speaker_order.sort(key=lambda s: speaker_durations[s], reverse=True)
    elif sort_by == "words":
        speaker_order.sort(key=lambda s: speaker_word_counts[s], reverse=True)
    elif sort_by == "wpm":
        speaker_order.sort(
            key=lambda s: speaker_wpm[s],
            reverse=True,
        )
    else:
        # default: sort alphabetically by speaker name
        speaker_order.sort()

    # calculate column widths dynamically
    speaker_col_label = "Speaker"
    all_names = [*speaker_order, "Total"]
    name_width = max(len(speaker_col_label), max(len(name) for name in all_names))

    words_col_label = "Words"
    duration_col_label = "Duration"
    wpm_col_label = "WPM"
    pct_col_label = "%"
    words_width = max(len(words_col_label), len(str(total_words)))
    duration_width = len(duration_col_label)
    wpm_width = max(len(wpm_col_label), len(str(total_wpm)))
    pct_width = max(len(pct_col_label), 4)  # "100%" is 4 chars

    # build the header line
    header_line = (
        f"  {speaker_col_label:<{name_width}}"
        f"  {words_col_label:>{words_width}}"
        f"  {duration_col_label:>{duration_width}}"
        f"  {wpm_col_label:>{wpm_width}}"
        f"  {pct_col_label:>{pct_width}}"
    )
    separator_width = len(header_line.rstrip())
    separator = "  " + "─" * (separator_width - 2)

    output_lines: list[str] = [
        f"# analysis: {source_name}",
        f"# duration: {duration_minutes} min",
        f"# speakers: {len(speaker_order)}",
        "",
        header_line.rstrip(),
        separator,
    ]

    for speaker in speaker_order:
        word_count = speaker_word_counts[speaker]
        duration_min = round(speaker_durations[speaker] / 60)
        duration_str = f"{duration_min} min"
        wpm = speaker_wpm[speaker]
        pct_str = f"{speaker_pct[speaker]}%"
        row = (
            f"  {speaker:<{name_width}}"
            f"  {word_count:>{words_width}}"
            f"  {duration_str:>{duration_width}}"
            f"  {wpm:>{wpm_width}}"
            f"  {pct_str:>{pct_width}}"
        )
        output_lines.append(row.rstrip())

    output_lines.append(separator)

    total_duration_min = round(total_duration_seconds / 60)
    total_duration_str = f"{total_duration_min} min"
    total_row = (
        f"  {'Total':<{name_width}}"
        f"  {total_words:>{words_width}}"
        f"  {total_duration_str:>{duration_width}}"
        f"  {total_wpm:>{wpm_width}}"
        f"  {'100%':>{pct_width}}"
    )
    output_lines.append(total_row.rstrip())

    return "\n".join(output_lines)


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


def summarize_vtt(
    vtt_path: str,
    output_path: str | None = None,
    model: str = "sonnet",
    system_prompt: str = SUMMARY_SYSTEM_PROMPT,
    base_url: str = DEFAULT_BASE_URL,
) -> None:
    """Summarize a VTT file using a local LLM via an OpenAI-compatible API."""
    vtt_file = Path(vtt_path)

    if not vtt_file.exists():
        print(f"[error] file '{vtt_path}' not found", file=sys.stderr)
        sys.exit(1)

    entries = parse_vtt(str(vtt_file))

    if not entries:
        print(f"[error] no entries found in '{vtt_path}'", file=sys.stderr)
        sys.exit(1)

    # build the transcript text for the LLM
    grouped = group_consecutive_messages(entries)
    header = format_header(vtt_file, entries)
    body = format_body(grouped)
    transcript_text = f"{header}\n\n{body}\n"

    # call LLM via OpenAI-compatible API — no sdk needed
    request_body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript_text},
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    summary_content = response_data["choices"][0]["message"]["content"]

    # build output metadata
    mtime = vtt_file.stat().st_mtime
    date_str = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d")
    duration = get_vtt_duration_minutes(vtt_file)
    speakers = extract_speakers(entries)
    speaker_list = ", ".join(speakers)
    source = vtt_file.name

    summary_header = "\n".join(
        [
            f"# date: {date_str}",
            f"# duration: {duration} min",
            f"# speakers: {speaker_list}",
            f"# source: {source}",
            "# type: summary",
        ]
    )
    output_text = f"{summary_header}\n\n{summary_content}\n"

    if output_path is None:
        output_path = format_summary_filename(vtt_file)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"{output_path}")


def analyze_command(vtt_path: str, sort_by: str = "speaker") -> None:
    """Validate file exists, parse with duration, and print speaker analysis."""
    vtt_file = Path(vtt_path)

    if not vtt_file.exists():
        print(f"[error] file '{vtt_path}' not found", file=sys.stderr)
        sys.exit(1)

    timed_entries = parse_vtt_with_duration(vtt_path)

    if not timed_entries:
        print(f"[error] no entries found in '{vtt_path}'", file=sys.stderr)
        sys.exit(1)

    analysis = analyze_speakers(timed_entries, vtt_file, sort_by)
    print(analysis)


def _generate_completion_script(shell: str) -> str:
    """Generate a shell completion script that auto-completes models from the API."""
    if shell == "bash":
        return """\
_vtt_completions() {
    local cur prev subcmd
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    subcmd="${COMP_WORDS[1]}"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=($(compgen -W "convert summary analyze models completions" -- "$cur"))
        return
    fi

    case "$subcmd" in
        convert)
            case "$prev" in
                *) COMPREPLY=($(compgen -f -X '!*.vtt' -- "$cur"))
                   COMPREPLY+=($(compgen -W "--output" -- "$cur")) ;;
            esac
            ;;
        summary)
            case "$prev" in
                --model|-m) COMPREPLY=($(compgen -W "$(vtt models 2>/dev/null)" -- "$cur")) ;;
                --prompt|-p) return ;;
                *) COMPREPLY=($(compgen -f -X '!*.vtt' -- "$cur"))
                   COMPREPLY+=($(compgen -W "--output --model --plan --prompt" -- "$cur")) ;;
            esac
            ;;
        analyze)
            case "$prev" in
                --sort|-s)
                    COMPREPLY=($(compgen -W "speaker duration words wpm" -- "$cur")) ;;
                *) COMPREPLY=($(compgen -f -X '!*.vtt' -- "$cur"))
                   COMPREPLY+=($(compgen -W "--sort" -- "$cur")) ;;
            esac
            ;;
        completions)
            COMPREPLY=($(compgen -W "bash zsh fish" -- "$cur"))
            ;;
    esac
}
complete -F _vtt_completions vtt"""
    if shell == "zsh":
        return """\
#compdef vtt

_vtt() {
    local -a subcmds
    subcmds=(convert summary analyze models completions)

    _arguments -C '1:command:compadd -a subcmds' '*::arg:->args'

    case $words[1] in
        convert)
            _arguments \\
                '1:vtt file:_files -g "*.vtt"' \\
                '--output[output file]:file:_files' \\
                '-o[output file]:file:_files'
            ;;
        summary)
            _arguments \\
                '1:vtt file:_files -g "*.vtt"' \\
                '--output[output file]:file:_files' \\
                '-o[output file]:file:_files' \\
                '--model[model name]:model:_vtt_models' \\
                '-m[model name]:model:_vtt_models' \\
                '--plan[extract action items]' \\
                '--prompt[custom system prompt]:prompt:' \\
                '-p[custom system prompt]:prompt:'
            ;;
        analyze)
            _arguments \\
                '1:vtt file:_files -g "*.vtt"' \\
                '--sort[sort column]:column:(speaker duration words wpm)' \\
                '-s[sort column]:column:(speaker duration words wpm)'
            ;;
        completions)
            _arguments '1:shell:(bash zsh fish)'
            ;;
    esac
}

_vtt_models() {
    local -a models
    models=(${(f)"$(vtt models 2>/dev/null)"})
    compadd -a models
}

_vtt"""
    if shell == "fish":
        return """\
# disable default file completions
complete -c vtt -f

# global options
complete -c vtt -n '__fish_use_subcommand' -s h -l help -d 'show help'

# subcommands
complete -c vtt -n '__fish_use_subcommand' -a convert -d 'convert VTT to plain text'
complete -c vtt -n '__fish_use_subcommand' -a summary -d 'summarize VTT via LLM'
complete -c vtt -n '__fish_use_subcommand' -a analyze -d 'analyze speaker statistics'
complete -c vtt -n '__fish_use_subcommand' -a models -d 'list available models'
complete -c vtt -n '__fish_use_subcommand' -a completions -d 'generate shell completions'

# convert options
complete -c vtt -n '__fish_seen_subcommand_from convert' -s o -l output -r -F
complete -c vtt -n '__fish_seen_subcommand_from convert' -F -a '(__fish_complete_suffix .vtt)'

# summary options
complete -c vtt -n '__fish_seen_subcommand_from summary' -s o -l output -r -F
complete -c vtt -n '__fish_seen_subcommand_from summary' -s m -l model -a '(vtt models 2>/dev/null)'
complete -c vtt -n '__fish_seen_subcommand_from summary' -s p -l prompt -d 'custom prompt'
complete -c vtt -n '__fish_seen_subcommand_from summary' -l plan -d 'extract action items'
complete -c vtt -n '__fish_seen_subcommand_from summary' -F -a '(__fish_complete_suffix .vtt)'

# analyze options
complete -c vtt -n '__fish_seen_subcommand_from analyze' \\
    -s s -l sort -a 'speaker duration words wpm'
complete -c vtt -n '__fish_seen_subcommand_from analyze' -F -a '(__fish_complete_suffix .vtt)'

# completions shell type
complete -c vtt -n '__fish_seen_subcommand_from completions' -a 'bash zsh fish'"""
    return ""


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

    # summary subcommand
    summary_parser = subparsers.add_parser(
        "summary",
        help="summarize VTT via LLM",
    )
    summary_parser.add_argument("vtt_file", help="path to VTT file")
    summary_parser.add_argument("--output", "-o", help="output file path")
    summary_parser.add_argument(
        "--model",
        "-m",
        default="sonnet",
        help="model name (default: sonnet)",
    )
    summary_parser.add_argument(
        "--plan",
        action="store_true",
        help="extract action items and decisions",
    )
    summary_parser.add_argument(
        "--prompt",
        "-p",
        help="custom system prompt",
    )
    summary_parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"OpenAI-compatible API base URL (default: {DEFAULT_BASE_URL})",
    )

    # analyze subcommand
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="analyze speaker statistics",
    )
    analyze_parser.add_argument("vtt_file", help="path to VTT file")
    analyze_parser.add_argument(
        "--sort",
        "-s",
        choices=["speaker", "duration", "words", "wpm"],
        default="speaker",
        help="sort by column (default: speaker)",
    )

    # models subcommand
    models_parser = subparsers.add_parser(
        "models",
        help="list available models",
    )
    models_parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"OpenAI-compatible API base URL (default: {DEFAULT_BASE_URL})",
    )

    # completions subcommand — emit shell completion script
    completions_parser = subparsers.add_parser(
        "completions",
        help="generate shell completion script",
    )
    completions_parser.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        help="shell type",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "convert":
        convert_vtt_to_txt(args.vtt_file, args.output)
    elif args.command == "summary":
        if args.prompt:
            system_prompt = args.prompt
        elif args.plan:
            system_prompt = PLAN_SYSTEM_PROMPT
        else:
            system_prompt = SUMMARY_SYSTEM_PROMPT
        summarize_vtt(args.vtt_file, args.output, args.model, system_prompt, args.base_url)
    elif args.command == "analyze":
        analyze_command(args.vtt_file, args.sort)
    elif args.command == "models":
        models = fetch_models(args.base_url)
        if not models:
            print(f"[error] could not reach API at {args.base_url}", file=sys.stderr)
            sys.exit(1)
        for model_name in models:
            print(model_name)
    elif args.command == "completions":
        print(_generate_completion_script(args.shell))


if __name__ == "__main__":
    main()
