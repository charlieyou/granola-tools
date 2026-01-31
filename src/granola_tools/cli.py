#!/usr/bin/env python3
"""Granola meeting search CLI."""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

INDEX_PATH = Path(os.getenv("GRANOLA_INDEX_PATH", "~/.granola/index/index.json")).expanduser()
TRANSCRIPTS_ROOT = Path(os.getenv("GRANOLA_TRANSCRIPTS_PATH", "~/.granola/transcripts")).expanduser()


def load_index():
    if not INDEX_PATH.exists():
        print(f"Index not found: {INDEX_PATH}", file=sys.stderr)
        print("Run build_index.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(INDEX_PATH.read_text())


def fmt_date(iso_str):
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return iso_str[:16]


def fmt_attendees(raw):
    if not raw:
        return ""
    names = []
    for a in raw[:5]:
        name = a.get("name") or a.get("email", "").split("@")[0]
        if name:
            names.append(name)
    result = ", ".join(names)
    if len(raw) > 5:
        result += f" +{len(raw)-5}"
    return result


def cmd_list(args):
    data = load_index()
    meetings = data["meetings"]
    
    # Filter by date if specified
    if args.date:
        meetings = [m for m in meetings if m.get("date_short") == args.date]
    elif args.today:
        today = datetime.now().strftime("%Y-%m-%d")
        meetings = [m for m in meetings if m.get("date_short") == today]
    elif args.yesterday:
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        meetings = [m for m in meetings if m.get("date_short") == yesterday]
    elif args.month:
        meetings = [m for m in meetings if m.get("date_short") and m.get("date_short").startswith(args.month)]
    elif args.since or args.until:
        filtered = []
        for m in meetings:
            ds = m.get("date_short")
            if not ds:
                continue
            if args.since and ds < args.since:
                continue
            if args.until and ds > args.until:
                continue
            filtered.append(m)
        meetings = filtered
    elif args.last:
        from datetime import timedelta
        days = int(args.last.rstrip("d"))
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        meetings = [m for m in meetings if m.get("date_short") and m.get("date_short") >= cutoff]
    
    # Sort by date descending
    meetings = sorted(meetings, key=lambda m: m.get("date_utc") or "", reverse=True)
    
    if args.limit and not (args.date or args.today or args.yesterday or args.since or args.until or args.last):
        meetings = meetings[:args.limit]
    
    if not meetings:
        print("No meetings found.")
        return
    
    for m in meetings:
        date = fmt_date(m.get("date_local") or m.get("date_utc"))
        title = m.get("title") or "(untitled)"
        transcript = "✓" if m.get("has_transcript") else " "
        short_id = m.get("short_id", m.get("id", "")[:7])
        print(f"{short_id}  {date}  [{transcript}]  {title[:55]}")


def cmd_search(args):
    data = load_index()
    query = args.query.lower()
    meetings = data["meetings"]
    
    results = []
    for m in meetings:
        title = (m.get("title") or "").lower()
        attendees = fmt_attendees(m.get("attendees_raw")).lower()
        if query in title or query in attendees:
            results.append(m)
    
    results = sorted(results, key=lambda m: m.get("date_utc") or "", reverse=True)
    
    if args.limit:
        results = results[:args.limit]
    
    if not results:
        print("No matches found.")
        return
    
    for m in results:
        date = fmt_date(m.get("date_local") or m.get("date_utc"))
        title = m.get("title") or "(untitled)"
        attendees = fmt_attendees(m.get("attendees_raw"))
        transcript = "✓" if m.get("has_transcript") else " "
        short_id = m.get("short_id", m.get("id", "")[:7])
        print(f"{short_id}  {date}  [{transcript}]  {title[:45]}")
        if attendees:
            print(f"                     {attendees[:55]}")
        print()


def find_meeting(data, query):
    """Find meeting by short ID, full ID, dir, or title match."""
    query_lower = query.lower()
    
    # Exact matches first
    for m in data["meetings"]:
        if m.get("short_id") == query or m.get("id") == query or m.get("dir") == query:
            return m
    
    # Partial ID match (starts with)
    for m in data["meetings"]:
        if m.get("id", "").startswith(query) or m.get("dir", "").startswith(query):
            return m
    
    # Title match
    for m in data["meetings"]:
        if query_lower in (m.get("title") or "").lower():
            return m
    
    return None


def cmd_show(args):
    data = load_index()
    match = find_meeting(data, args.query)
    
    if not match:
        print(f"Meeting not found: {args.query}", file=sys.stderr)
        sys.exit(1)
    
    # Print metadata
    short_id = match.get("short_id", match.get("id", "")[:7])
    print(f"ID:         {short_id} ({match.get('id')})")
    print(f"Title:      {match.get('title')}")
    print(f"Date:       {fmt_date(match.get('date_local') or match.get('date_utc'))}")
    print(f"Duration:   {match.get('duration_min') or '?'} min")
    print(f"Attendees:  {fmt_attendees(match.get('attendees_raw'))}")
    print(f"Transcript: {'Yes' if match.get('has_transcript') else 'No'}")
    print(f"Resume:     {'Yes' if match.get('has_resume') else 'No'}")
    
    folder = TRANSCRIPTS_ROOT / match.get("dir")
    print(f"Path:       {folder}")


def cmd_transcript(args):
    data = load_index()
    match = find_meeting(data, args.query)
    
    if not match:
        print(f"Meeting not found: {args.query}", file=sys.stderr)
        sys.exit(1)
    
    folder = TRANSCRIPTS_ROOT / match.get("dir")
    transcript_md = folder / "transcript.md"
    transcript_json = folder / "transcript.json"
    
    if transcript_md.exists():
        print(transcript_md.read_text())
    elif transcript_json.exists():
        tdata = json.loads(transcript_json.read_text())
        for u in tdata:
            source = u.get("source", "?")
            text = u.get("text", "")
            print(f"[{source}] {text}\n")
    else:
        print("No transcript available.", file=sys.stderr)
        sys.exit(1)


def cmd_resume(args):
    data = load_index()
    match = find_meeting(data, args.query)
    
    if not match:
        print(f"Meeting not found: {args.query}", file=sys.stderr)
        sys.exit(1)
    
    folder = TRANSCRIPTS_ROOT / match.get("dir")
    resume = folder / "resume.md"
    
    if resume.exists():
        print(resume.read_text())
    else:
        print("No resume available.", file=sys.stderr)
        sys.exit(1)


def cmd_stats(args):
    data = load_index()
    meetings = data["meetings"]
    
    total = len(meetings)
    with_transcript = sum(1 for m in meetings if m.get("has_transcript"))
    with_resume = sum(1 for m in meetings if m.get("has_resume"))
    
    # By month
    by_month = {}
    for m in meetings:
        key = f"{m.get('year')}-{m.get('month'):02d}" if m.get("year") and m.get("month") else "unknown"
        by_month[key] = by_month.get(key, 0) + 1
    
    print(f"Total meetings:    {total}")
    print(f"With transcript:   {with_transcript}")
    print(f"With resume:       {with_resume}")
    print(f"Index generated:   {data.get('generated_at', '?')}")
    print()
    print("By month:")
    for k in sorted(by_month.keys(), reverse=True)[:12]:
        print(f"  {k}: {by_month[k]}")


def main():
    parser = argparse.ArgumentParser(description="Granola meeting search CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # list
    p_list = subparsers.add_parser("list", aliases=["ls"], help="List recent meetings")
    p_list.add_argument("-n", "--limit", type=int, default=20, help="Max results")
    p_list.add_argument("-d", "--date", help="Filter by date (YYYY-MM-DD)")
    p_list.add_argument("--today", action="store_true", help="Show today's meetings")
    p_list.add_argument("--yesterday", action="store_true", help="Show yesterday's meetings")
    p_list.add_argument("-m", "--month", help="Filter by month (YYYY-MM)")
    p_list.add_argument("--since", help="From date (YYYY-MM-DD)")
    p_list.add_argument("--until", help="To date (YYYY-MM-DD)")
    p_list.add_argument("--last", help="Last N days (e.g. 7d)")
    p_list.set_defaults(func=cmd_list)
    
    # search
    p_search = subparsers.add_parser("search", aliases=["s"], help="Search meetings")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("-n", "--limit", type=int, default=20, help="Max results")
    p_search.set_defaults(func=cmd_search)
    
    # show
    p_show = subparsers.add_parser("show", help="Show meeting details")
    p_show.add_argument("query", help="Meeting title or ID")
    p_show.set_defaults(func=cmd_show)
    
    # transcript
    p_trans = subparsers.add_parser("transcript", aliases=["t"], help="Show transcript")
    p_trans.add_argument("query", help="Meeting title or ID")
    p_trans.set_defaults(func=cmd_transcript)
    
    # resume
    p_resume = subparsers.add_parser("resume", aliases=["r"], help="Show resume/notes")
    p_resume.add_argument("query", help="Meeting title or ID")
    p_resume.set_defaults(func=cmd_resume)
    
    # stats
    p_stats = subparsers.add_parser("stats", help="Show index statistics")
    p_stats.set_defaults(func=cmd_stats)
    
    # sync
    p_sync = subparsers.add_parser("sync", help="Sync meetings from Granola API")
    p_sync.add_argument("output_dir", nargs="?", default=str(TRANSCRIPTS_ROOT), help="Output directory")
    p_sync.add_argument("--full", action="store_true", help="Force full sync")
    p_sync.set_defaults(func=cmd_sync)
    
    # index
    p_index = subparsers.add_parser("index", help="Rebuild search index")
    p_index.set_defaults(func=cmd_index)
    
    args = parser.parse_args()
    args.func(args)


def cmd_sync(args):
    from .sync import run_sync
    run_sync(args.output_dir, full=args.full)


def cmd_index(args):
    from .index import build_index
    build_index()


if __name__ == "__main__":
    main()
