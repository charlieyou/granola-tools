# Granola Tools

CLI for syncing and browsing Granola meeting transcripts.

Based on [getprobo/reverse-engineering-granola-api](https://github.com/getprobo/reverse-engineering-granola-api).

## Installation

```bash
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

```bash
# Sync meetings from Granola API
granola sync

# Rebuild local index
granola index

# List recent meetings
granola ls
granola ls -n 50
granola ls --today
granola ls --yesterday
granola ls --last 7d
granola ls -d 2024-01-15
granola ls --since 2024-01-01 --until 2024-01-31

# Show meeting details
granola show <id>
granola show "meeting title"

# View transcript or notes
granola t <id>      # transcript
granola r <id>      # resume/notes

# Stats
granola stats
```

## Search with qmd

For full-text and semantic search, use [qmd](https://github.com/tobi/qmd):

```bash
# One-time setup
qmd collection add ~/.granola/transcripts --name granola --mask "**/*.md"
qmd embed  # generate vector embeddings

# Search
qmd search "pricing discussion" -c granola          # BM25 full-text
qmd vsearch "what did we decide about X" -c granola # semantic
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
        ├── metadata.json
        ├── transcript.md
        └── resume.md
```
