---
name: searching-granola-meetings
description: "Syncs, lists, filters, and retrieves Granola meeting transcripts/notes via CLI. Use when finding meetings by date/title/attendee, pulling transcripts or notes, or refreshing local data. Triggers: granola, meeting transcript, meeting notes, standup, sync call, find meeting, pull transcript."
---

# Searching Granola Meetings

## List meetings

```bash
granola ls                  # recent 10
granola ls -n 5             # limit results, composable with all other flags on ls
```

## Filter by date

```bash
granola ls --today
granola ls --yesterday
granola ls --last 7d
granola ls -d 2024-01-15
granola ls -m 2024-01
granola ls --since 2024-01-01 --until 2024-01-31
```

## Filter by title or attendee

```bash
granola ls -t "data sync"
granola ls -a Charlie
granola ls --last 30d -a Charlie -t sync -n 5
```

## View meeting

```bash
granola show e9053e5        # by short ID
granola show "Standup"      # by title match
granola t <id>              # transcript
granola notes <id>          # notes
granola show <id> --json
```

## JSON output

```bash
granola ls --json | jq '.[0].title'

# Print all transcripts from a search
granola ls --last 7d -a Adam --json | jq -r '.[].short_id' | xargs -I{} granola t {}
```

Fields: `id`, `short_id`, `title`, `date_utc`, `date_local`, `date_short`, `duration_min`, `path`, `transcript_path`, `notes_path`, `has_transcript`, `has_notes`, `attendees_raw`
