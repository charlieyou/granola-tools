# Granola Tools

CLI for syncing and searching Granola meeting transcripts.

## Installation

```bash
uv tool install -e .
```

## Configuration

Create a `.env` file:

```bash
GRANOLA_REFRESH_TOKEN=your_refresh_token
GRANOLA_CLIENT_ID=client_your_client_id
GRANOLA_TRANSCRIPTS_PATH=~/Documents/granola-transcripts
GRANOLA_INDEX_PATH=~/Documents/granola-search/state/index.json
```

See `docs/GETTING_REFRESH_TOKEN.md` for token setup.

## Usage

```bash
# Sync meetings from Granola API
granola-sync ~/Documents/granola-transcripts

# List recent meetings
granola ls
granola ls -n 50
granola ls --today
granola ls --last 7d
granola ls -d 2024-01-15
granola ls --since 2024-01-01 --until 2024-01-31

# Search meetings
granola search "keyword"
granola search "person name"

# Show meeting details
granola show <short_id>
granola show "meeting title"

# View transcript or notes
granola transcript <short_id>
granola resume <short_id>

# Stats
granola stats
```

## Cron Setup

```bash
# Run every 30 minutes
*/30 * * * * ~/code/granola-tools/sync_and_index.sh >> ~/code/granola-tools/cron.log 2>&1
```
