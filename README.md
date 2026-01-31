# Granola Tools

CLI for syncing and searching Granola meeting transcripts locally.

> **Compatibility:** macOS only. Tested with Granola v5.354.0 (January 2026).
> This tool uses Granola's internal API which may change without notice.

## Installation

```bash
git clone https://github.com/charlieyou/granola-tools
cd granola-tools
uv tool install -e .
```

## Setup

**Prerequisite:** Sign into the [Granola](https://granola.ai) desktop app first.

```bash
granola init
```

This will:
1. Ask where to store data (default: `~/.granola`)
2. Create necessary directories
3. Extract credentials from the Granola app
4. Perform initial sync

Config is stored in `~/.granola/config.json`.

## Usage

### Sync & Index

```bash
granola sync          # Sync meetings from Granola API
granola sync --full   # Force full sync (ignore incremental state)
granola index         # Rebuild local search index
```

### List Meetings

```bash
granola ls                        # List recent meetings (default: 10)
granola ls -n 50                  # Limit results
granola ls -n 0                   # Unlimited

# Date filters
granola ls --today
granola ls --yesterday
granola ls --last 7d
granola ls -d 2024-01-15          # Specific date
granola ls -m 2024-01             # Specific month
granola ls --since 2024-01-01 --until 2024-01-31

# Filter by attendee (partial match on name/email)
granola ls -a Adam
granola ls --attendee bryan@example.com

# Fuzzy search by title (all words must match)
granola ls -t "data sync"
granola ls -t standup --last 7d

# Combine filters
granola ls --last 30d -a Adam -t sync -n 5

# JSON output for scripting
granola ls --json | jq '.[0].title'
```

### View Meetings

```bash
granola show <id>           # Show meeting details
granola show e9053e5        # By short ID
granola show "Standup"      # By title match

granola t <id>              # Print transcript
granola notes <id>          # Print notes

# JSON output
granola show <id> --json
```

### Stats

```bash
granola stats               # Index statistics
granola stats --json
```

## Output Format

```
$ granola ls -n 2
e9053e5  2026-01-30 14:00  (15 min)  Standup
  Alice <alice@example.com>, Bob <bob@example.com>

0b23dc5  2026-01-29 14:00  (15 min)  Weekly Sync
  Alice <alice@example.com>, Charlie <charlie@example.com>
```

## JSON Schema

Each meeting in `granola ls --json` includes:

```json
{
  "id": "e9053e52-d939-406f-8284-b04652d28bb3",
  "short_id": "e9053e5",
  "title": "Standup",
  "date_utc": "2026-01-30T19:00:00Z",
  "date_local": "2026-01-30T14:00:00-05:00",
  "date_short": "2026-01-30",
  "duration_min": 15,
  "path": "/Users/you/.granola/transcripts/e9053e52-...",
  "transcript_path": "/Users/you/.granola/transcripts/e9053e52-.../transcript.md",
  "notes_path": "/Users/you/.granola/transcripts/e9053e52-.../resume.md",
  "has_transcript": true,
  "has_notes": true,
  "attendees_raw": [...]
}
```

## Search with qmd

For full-text and semantic search across transcripts, use [qmd](https://github.com/tobi/qmd):

```bash
# One-time setup
qmd collection add ~/.granola/transcripts --name granola --mask "**/transcript.md"
qmd embed  # generate vector embeddings

# Search
qmd search "pricing discussion" -c granola            # BM25 full-text
qmd vsearch "what did we decide about X" -c granola   # semantic
qmd query "action items from last standup" -c granola # hybrid + reranking
```

The path in results contains the meeting UUID — use `granola show <uuid>` for metadata.

## Cron

```bash
# Sync every 30 minutes
*/30 * * * * ~/.local/bin/granola sync && ~/.local/bin/granola index
```

**Important:** Cron should run at least every hour. The refresh token is rotated on each sync — if unused for too long, it may expire and require re-running `granola init`.

## Data Location

```
~/.granola/
├── config.json         # Credentials & settings
├── sync.log            # Sync log
├── index/
│   └── index.json      # Meeting metadata index
└── transcripts/
    └── <uuid>/         # Per-meeting folder
        ├── document.json
        ├── metadata.json
        ├── transcript.md
        ├── transcript.json
        └── resume.md   # Notes
```

## Credits

Based on [getprobo/reverse-engineering-granola-api](https://github.com/getprobo/reverse-engineering-granola-api).
