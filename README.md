# vtt

A Python CLI toolkit for working with WebVTT transcript files. Convert to plain text, analyze speaker statistics, and generate AI-powered meeting summaries.

## Features

- **Convert** VTT files to timestamped plain text with metadata headers
- **Analyze** speaker participation (word count, duration, WPM, percentage)
- **Summarize** meetings via LLM with built-in summary and plan-extraction prompts
- **CJK-aware** word counting for multilingual transcripts
- **Shell completions** for bash, zsh, and fish

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [litellm proxy](https://docs.litellm.ai/) on `localhost:4000` or any OpenAI-compatible API (optional, for `summary` and `models` commands)

## Installation

```bash
just install

# or install shell completions separately (auto-detects shell)
just install-completions
just install-completions fish
```

## Usage

### Convert VTT to plain text

```bash
vtt convert meeting.vtt
vtt convert meeting.vtt --output transcript.txt
```

Produces an IRC-style transcript with a metadata header (date, duration, speakers, source):

```
date:     2026-04-07
duration: 1h 14m
speakers: Alice, Bob, Charlie
source:   meeting.vtt

[09:00:05] Alice: Good morning everyone
[09:00:12] Bob: Hey, let's get started
```

### Analyze speaker statistics

```bash
vtt analyze meeting.vtt
vtt analyze meeting.vtt --sort duration
```

Sort by `speaker` (default), `duration`, `words`, or `wpm`.

```
Speaker       Words   Duration   WPM    %
Alice           842    12m 30s    67   16.9
Bob            1205    18m 45s    64   25.4
...
Total          4680  1h 14m 00s    63  100.0
```

### Summarize with LLM

```bash
vtt summary meeting.vtt
vtt summary meeting.vtt --model sonnet
vtt summary meeting.vtt --plan              # extract action items and decisions
vtt summary meeting.vtt --prompt "List only the action items"

# use Ollama or any OpenAI-compatible API
vtt summary meeting.vtt --base-url http://localhost:11434/v1 --model llama3
vtt models --base-url http://localhost:11434/v1
```

### List available models

```bash
vtt models
```

### Generate shell completions

```bash
vtt completions fish | source
vtt completions zsh > ~/.zsh/completions/_vtt
```

## Development

```bash
just check      # format + lint + typecheck + test
just test       # pytest
just lint       # ruff check
just format     # ruff format
just typecheck  # mypy
```

## License

MIT
