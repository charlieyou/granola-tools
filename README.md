# Granola Tools

CLI for syncing and browsing Granola meeting transcripts.

Based on [getprobo/reverse-engineering-granola-api](https://github.com/getprobo/reverse-engineering-granola-api).

## Installation

```bash
git clone https://github.com/charlieyou/granola-tools
cd granola-tools
uv tool install -e .
```

## Configuration

Create a `.env` file in the repo or `~/.config/granola/.env`:

```bash
GRANOLA_REFRESH_TOKEN=your_refresh_token
GRANOLA_CLIENT_ID=your_client_id
# Optional - defaults to ~/.granola
GRANOLA_HOME=~/.granola
```

To get tokens, extract from `~/Library/Application Support/Granola/supabase.json` after logging into Granola:

```bash
# Extract refresh token
cat ~/Library/Application\ Support/Granola/supabase.json | jq -r '.workos_tokens | fromjson | .refresh_token'

# Extract client_id from JWT
cat ~/Library/Application\ Support/Granola/supabase.json | jq -r '.workos_tokens | fromjson | .access_token' | cut -d. -f2 | base64 -d 2>/dev/null | jq -r '.iss' | grep -o 'client_[^"]*'
```

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
granola ls --attendee bryan@rwa.xyz

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
granola r <id>              # Print notes/resume

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
  Pasha <pasha@rwa.xyz>, Devang Patel <devang@rwa.xyz>, Adam Lawrence <adam@rwa.xyz>

0b23dc5  2026-01-29 14:00  (15 min)  Standup
  Pasha <pasha@rwa.xyz>, Devang Patel <devang@rwa.xyz>, Adam Lawrence <adam@rwa.xyz>
```

## Search with qmd

For full-text and semantic search across transcripts, use [qmd](https://github.com/tobi/qmd):

```bash
# One-time setup
qmd collection add ~/.granola/transcripts --name granola --mask "**/*.md"
qmd embed  # generate vector embeddings

# Search
qmd search "pricing discussion" -c granola            # BM25 full-text
qmd vsearch "what did we decide about X" -c granola   # semantic
qmd query "action items from last standup" -c granola # hybrid + reranking
```

The path in results contains the meeting UUID — use `granola show <uuid>` for metadata.

## Cron

```bash
# Sync every 30 minutes, update qmd index + embeddings
*/30 * * * * ~/.local/bin/granola sync && ~/.local/bin/granola index && qmd update -c granola && qmd embed -c granola
```

**Important:** Cron must run at least every hour. The refresh token is rotated on each sync to keep the session alive — if it's not used within ~1 hour, it expires and you'll need to re-extract tokens from Granola.

`qmd embed` is incremental (content-hash based) — first run is slow, subsequent runs only process new/changed files.

## Data Location

```
~/.granola/
├── index/
│   └── index.json      # Meeting metadata index
└── transcripts/
    └── <uuid>/         # Per-meeting folder
        ├── document.json
        ├── metadata.json
        ├── transcript.md
        ├── transcript.json
        └── resume.md
```
