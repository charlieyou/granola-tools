#!/usr/bin/env python3
"""Granola meeting search CLI."""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(help="CLI for Granola meeting transcripts", add_completion=False)

GRANOLA_HOME = Path(os.getenv("GRANOLA_HOME", "~/.granola")).expanduser()
INDEX_PATH = GRANOLA_HOME / "index" / "index.json"
TRANSCRIPTS_ROOT = GRANOLA_HOME / "transcripts"


def load_index():
    if not INDEX_PATH.exists():
        sys.stderr.write(f"error: index not found: {INDEX_PATH}\n")
        sys.stderr.write("Run 'granola sync' and 'granola index' first.\n")
        raise typer.Exit(1)
    return json.loads(INDEX_PATH.read_text())


def fmt_date(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return iso_str[:16]


def fmt_attendees(raw: Optional[list]) -> str:
    """Format attendees like calendar: Name <email>"""
    if not raw:
        return ""
    parts = []
    for a in raw:
        name = a.get("name") or ""
        email = a.get("email") or ""
        # Try to get fullName from details
        details = a.get("details", {})
        person = details.get("person", {})
        name_obj = person.get("name", {})
        if name_obj.get("fullName"):
            name = name_obj["fullName"]
        
        if name and email:
            parts.append(f"{name} <{email}>")
        elif email:
            parts.append(email)
        elif name:
            parts.append(name)
    
    return ", ".join(parts)


def get_attendee_strings(m: dict) -> list[str]:
    """Extract all searchable attendee strings (names and emails) from a meeting."""
    strings = []
    for a in m.get("attendees_raw") or []:
        if a.get("name"):
            strings.append(a["name"].lower())
        if a.get("email"):
            strings.append(a["email"].lower())
        details = a.get("details", {})
        person = details.get("person", {})
        name_obj = person.get("name", {})
        if name_obj.get("fullName"):
            strings.append(name_obj["fullName"].lower())
    return strings


def find_meeting(data: dict, query: str):
    """Find meeting by short ID, full ID, dir, or title match."""
    query_lower = query.lower()
    
    # Exact ID matches first
    for m in data["meetings"]:
        if m.get("short_id") == query or m.get("id") == query or m.get("dir") == query:
            return m
    
    # Prefix match on ID
    for m in data["meetings"]:
        if m.get("id", "").startswith(query) or m.get("dir", "").startswith(query):
            return m
    
    # Title substring match
    for m in data["meetings"]:
        if query_lower in (m.get("title") or "").lower():
            return m
    
    return None


def filter_meetings(
    meetings: list,
    date: Optional[str] = None,
    today: bool = False,
    yesterday: bool = False,
    month: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    last: Optional[str] = None,
    attendee: Optional[str] = None,
) -> list:
    """Apply filters to meeting list. Filters are ANDed together."""
    result = meetings
    
    # Date filters (mutually exclusive)
    if date:
        result = [m for m in result if m.get("date_short") == date]
    elif today:
        today_str = datetime.now().strftime("%Y-%m-%d")
        result = [m for m in result if m.get("date_short") == today_str]
    elif yesterday:
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        result = [m for m in result if m.get("date_short") == yesterday_str]
    elif month:
        result = [m for m in result if m.get("date_short") and m.get("date_short").startswith(month)]
    elif last:
        days = int(last.rstrip("d"))
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        result = [m for m in result if m.get("date_short") and m.get("date_short") >= cutoff]
    elif since or until:
        filtered = []
        for m in result:
            ds = m.get("date_short")
            if not ds:
                continue
            if since and ds < since:
                continue
            if until and ds > until:
                continue
            filtered.append(m)
        result = filtered
    
    # Attendee filter (can combine with date filters)
    if attendee:
        attendee_lower = attendee.lower()
        result = [m for m in result if any(attendee_lower in s for s in get_attendee_strings(m))]
    
    return result


@app.command("ls")
@app.command("list", hidden=True)
def list_meetings(
    limit: int = typer.Option(20, "-n", "--limit", help="Max results (0 for unlimited)"),
    date: Optional[str] = typer.Option(None, "-d", "--date", help="Filter by date (YYYY-MM-DD)"),
    today: bool = typer.Option(False, "--today", help="Show today's meetings"),
    yesterday: bool = typer.Option(False, "--yesterday", help="Show yesterday's meetings"),
    month: Optional[str] = typer.Option(None, "-m", "--month", help="Filter by month (YYYY-MM)"),
    since: Optional[str] = typer.Option(None, "--since", help="From date inclusive (YYYY-MM-DD)"),
    until: Optional[str] = typer.Option(None, "--until", help="To date inclusive (YYYY-MM-DD)"),
    last: Optional[str] = typer.Option(None, "--last", help="Last N days (e.g. 7d)"),
    attendee: Optional[str] = typer.Option(None, "-a", "--attendee", help="Filter by attendee name/email"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List meetings, sorted by date descending.
    
    JSON schema: [{
      id: string,
      short_id: string,
      title: string,
      date_utc: string (ISO 8601),
      date_local: string (ISO 8601),
      date_short: string (YYYY-MM-DD),
      year: number,
      month: number,
      duration_min: number | null,
      has_transcript: boolean,
      has_resume: boolean,
      path: string (full path to meeting dir),
      attendees_raw: [{
        name?: string,
        email: string,
        details?: {
          person?: {
            name?: {fullName: string, givenName?: string, familyName?: string},
            avatar?: string,
            employment?: {name: string, title: string},
            linkedin?: {handle: string}
          },
          company?: {name?: string}
        }
      }]
    }]
    """
    data = load_index()
    meetings = data["meetings"]
    
    # Apply filters
    meetings = filter_meetings(
        meetings,
        date=date, today=today, yesterday=yesterday,
        month=month, since=since, until=until, last=last,
        attendee=attendee,
    )
    
    # Sort by date descending
    meetings = sorted(meetings, key=lambda m: m.get("date_utc") or "", reverse=True)
    
    # Apply limit (always, unless 0)
    if limit > 0:
        meetings = meetings[:limit]
    
    if output_json:
        for m in meetings:
            m["path"] = str(TRANSCRIPTS_ROOT / m.get("dir", ""))
        print(json.dumps(meetings))
        return
    
    if not meetings:
        return  # No output for empty results (Unix convention)
    
    for m in meetings:
        dt = fmt_date(m.get("date_local") or m.get("date_utc"))
        title = m.get("title") or "(untitled)"
        transcript = "✓" if m.get("has_transcript") else " "
        short_id = m.get("short_id", m.get("id", "")[:7])
        attendees = fmt_attendees(m.get("attendees_raw"))
        print(f"{short_id}  {dt}  [{transcript}]  {title[:50]}")
        if attendees:
            print(f"         {attendees}")


@app.command()
def show(
    query: str = typer.Argument(..., help="Meeting ID, short ID, or title"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show meeting details.
    
    JSON schema: {
      id: string,
      short_id: string,
      title: string,
      date_utc: string (ISO 8601),
      date_local: string (ISO 8601),
      date_short: string (YYYY-MM-DD),
      year: number,
      month: number,
      duration_min: number | null,
      has_transcript: boolean,
      has_resume: boolean,
      path: string (full path to meeting dir),
      attendees_raw: [{
        name?: string,
        email: string,
        details?: {
          person?: {
            name?: {fullName: string, givenName?: string, familyName?: string},
            avatar?: string,
            employment?: {name: string, title: string},
            linkedin?: {handle: string}
          },
          company?: {name?: string}
        }
      }]
    }
    """
    data = load_index()
    match = find_meeting(data, query)
    
    if not match:
        sys.stderr.write(f"error: meeting not found: {query}\n")
        raise typer.Exit(1)
    
    if output_json:
        match["path"] = str(TRANSCRIPTS_ROOT / match.get("dir", ""))
        print(json.dumps(match))
        return
    
    short_id = match.get("short_id", match.get("id", "")[:7])
    print(f"ID:         {short_id} ({match.get('id')})")
    print(f"Title:      {match.get('title')}")
    print(f"Date:       {fmt_date(match.get('date_local') or match.get('date_utc'))}")
    print(f"Duration:   {match.get('duration_min') or '?'} min")
    print(f"Attendees:  {fmt_attendees(match.get('attendees_raw'))}")
    print(f"Transcript: {'yes' if match.get('has_transcript') else 'no'}")
    print(f"Resume:     {'yes' if match.get('has_resume') else 'no'}")
    print(f"Path:       {TRANSCRIPTS_ROOT / match.get('dir')}")


@app.command("t")
@app.command("transcript", hidden=True)
def transcript(query: str = typer.Argument(..., help="Meeting ID, short ID, or title")):
    """Print meeting transcript to stdout."""
    data = load_index()
    match = find_meeting(data, query)
    
    if not match:
        sys.stderr.write(f"error: meeting not found: {query}\n")
        raise typer.Exit(1)
    
    folder = TRANSCRIPTS_ROOT / match.get("dir")
    transcript_md = folder / "transcript.md"
    transcript_json = folder / "transcript.json"
    
    if transcript_md.exists():
        print(transcript_md.read_text(), end="")
    elif transcript_json.exists():
        tdata = json.loads(transcript_json.read_text())
        for u in tdata:
            source = u.get("source", "?")
            text = u.get("text", "")
            print(f"[{source}] {text}\n")
    else:
        sys.stderr.write("error: no transcript available\n")
        raise typer.Exit(1)


@app.command("r")
@app.command("resume", hidden=True)
def resume(query: str = typer.Argument(..., help="Meeting ID, short ID, or title")):
    """Print meeting notes/resume to stdout."""
    data = load_index()
    match = find_meeting(data, query)
    
    if not match:
        sys.stderr.write(f"error: meeting not found: {query}\n")
        raise typer.Exit(1)
    
    folder = TRANSCRIPTS_ROOT / match.get("dir")
    resume_file = folder / "resume.md"
    
    if resume_file.exists():
        print(resume_file.read_text(), end="")
    else:
        sys.stderr.write("error: no resume available\n")
        raise typer.Exit(1)


@app.command()
def stats(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show index statistics.
    
    JSON schema: {
      total: number,
      with_transcript: number,
      with_resume: number,
      generated_at: string (ISO 8601),
      by_month: {[YYYY-MM: string]: number}
    }
    """
    data = load_index()
    meetings = data["meetings"]
    
    total = len(meetings)
    with_transcript = sum(1 for m in meetings if m.get("has_transcript"))
    with_resume = sum(1 for m in meetings if m.get("has_resume"))
    
    by_month = {}
    for m in meetings:
        key = f"{m.get('year')}-{m.get('month'):02d}" if m.get("year") and m.get("month") else "unknown"
        by_month[key] = by_month.get(key, 0) + 1
    
    if output_json:
        print(json.dumps({
            "total": total,
            "with_transcript": with_transcript,
            "with_resume": with_resume,
            "generated_at": data.get("generated_at"),
            "by_month": by_month,
        }))
        return
    
    print(f"Total meetings:    {total}")
    print(f"With transcript:   {with_transcript}")
    print(f"With resume:       {with_resume}")
    print(f"Index generated:   {data.get('generated_at', '?')}")
    print()
    print("By month:")
    for k in sorted(by_month.keys(), reverse=True)[:12]:
        print(f"  {k}: {by_month[k]}")


@app.command()
def sync(
    output_dir: Optional[str] = typer.Argument(None, help="Output directory"),
    full: bool = typer.Option(False, "--full", help="Force full sync (ignore incremental state)"),
):
    """Sync meetings from Granola API."""
    from .sync import run_sync
    run_sync(output_dir or str(TRANSCRIPTS_ROOT), full=full)


@app.command()
def index():
    """Rebuild the search index from synced transcripts."""
    from .index import build_index
    build_index()


def main():
    app()


if __name__ == "__main__":
    main()
