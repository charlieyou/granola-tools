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

app = typer.Typer(help="Granola meeting search CLI")

GRANOLA_HOME = Path(os.getenv("GRANOLA_HOME", "~/.granola")).expanduser()
INDEX_PATH = GRANOLA_HOME / "index" / "index.json"
TRANSCRIPTS_ROOT = GRANOLA_HOME / "transcripts"


def load_index():
    if not INDEX_PATH.exists():
        typer.echo(f"Index not found: {INDEX_PATH}", err=True)
        typer.echo("Run 'granola sync' and 'granola index' first.", err=True)
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


def find_meeting(data: dict, query: str):
    """Find meeting by short ID, full ID, dir, or title match."""
    query_lower = query.lower()
    
    for m in data["meetings"]:
        if m.get("short_id") == query or m.get("id") == query or m.get("dir") == query:
            return m
    
    for m in data["meetings"]:
        if m.get("id", "").startswith(query) or m.get("dir", "").startswith(query):
            return m
    
    for m in data["meetings"]:
        if query_lower in (m.get("title") or "").lower():
            return m
    
    return None


@app.command("ls")
@app.command("list", hidden=True)
def list_meetings(
    limit: int = typer.Option(20, "-n", "--limit", help="Max results"),
    date: Optional[str] = typer.Option(None, "-d", "--date", help="Filter by date (YYYY-MM-DD)"),
    today: bool = typer.Option(False, "--today", help="Show today's meetings"),
    yesterday: bool = typer.Option(False, "--yesterday", help="Show yesterday's meetings"),
    month: Optional[str] = typer.Option(None, "-m", "--month", help="Filter by month (YYYY-MM)"),
    since: Optional[str] = typer.Option(None, "--since", help="From date (YYYY-MM-DD)"),
    until: Optional[str] = typer.Option(None, "--until", help="To date (YYYY-MM-DD)"),
    last: Optional[str] = typer.Option(None, "--last", help="Last N days (e.g. 7d)"),
):
    """List recent meetings."""
    data = load_index()
    meetings = data["meetings"]
    
    if date:
        meetings = [m for m in meetings if m.get("date_short") == date]
    elif today:
        today_str = datetime.now().strftime("%Y-%m-%d")
        meetings = [m for m in meetings if m.get("date_short") == today_str]
    elif yesterday:
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        meetings = [m for m in meetings if m.get("date_short") == yesterday_str]
    elif month:
        meetings = [m for m in meetings if m.get("date_short") and m.get("date_short").startswith(month)]
    elif since or until:
        filtered = []
        for m in meetings:
            ds = m.get("date_short")
            if not ds:
                continue
            if since and ds < since:
                continue
            if until and ds > until:
                continue
            filtered.append(m)
        meetings = filtered
    elif last:
        days = int(last.rstrip("d"))
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        meetings = [m for m in meetings if m.get("date_short") and m.get("date_short") >= cutoff]
    
    meetings = sorted(meetings, key=lambda m: m.get("date_utc") or "", reverse=True)
    
    if limit and not (date or today or yesterday or since or until or last):
        meetings = meetings[:limit]
    
    if not meetings:
        typer.echo("No meetings found.")
        return
    
    for m in meetings:
        dt = fmt_date(m.get("date_local") or m.get("date_utc"))
        title = m.get("title") or "(untitled)"
        transcript = "✓" if m.get("has_transcript") else " "
        short_id = m.get("short_id", m.get("id", "")[:7])
        typer.echo(f"{short_id}  {dt}  [{transcript}]  {title[:55]}")


@app.command()
def show(query: str = typer.Argument(..., help="Meeting title or ID")):
    """Show meeting details."""
    data = load_index()
    match = find_meeting(data, query)
    
    if not match:
        typer.echo(f"Meeting not found: {query}", err=True)
        raise typer.Exit(1)
    
    short_id = match.get("short_id", match.get("id", "")[:7])
    typer.echo(f"ID:         {short_id} ({match.get('id')})")
    typer.echo(f"Title:      {match.get('title')}")
    typer.echo(f"Date:       {fmt_date(match.get('date_local') or match.get('date_utc'))}")
    typer.echo(f"Duration:   {match.get('duration_min') or '?'} min")
    typer.echo(f"Attendees:  {fmt_attendees(match.get('attendees_raw'))}")
    typer.echo(f"Transcript: {'Yes' if match.get('has_transcript') else 'No'}")
    typer.echo(f"Resume:     {'Yes' if match.get('has_resume') else 'No'}")
    typer.echo(f"Path:       {TRANSCRIPTS_ROOT / match.get('dir')}")


@app.command("t")
@app.command("transcript", hidden=True)
def transcript(query: str = typer.Argument(..., help="Meeting title or ID")):
    """Show meeting transcript."""
    data = load_index()
    match = find_meeting(data, query)
    
    if not match:
        typer.echo(f"Meeting not found: {query}", err=True)
        raise typer.Exit(1)
    
    folder = TRANSCRIPTS_ROOT / match.get("dir")
    transcript_md = folder / "transcript.md"
    transcript_json = folder / "transcript.json"
    
    if transcript_md.exists():
        typer.echo(transcript_md.read_text())
    elif transcript_json.exists():
        tdata = json.loads(transcript_json.read_text())
        for u in tdata:
            source = u.get("source", "?")
            text = u.get("text", "")
            typer.echo(f"[{source}] {text}\n")
    else:
        typer.echo("No transcript available.", err=True)
        raise typer.Exit(1)


@app.command("r")
@app.command("resume", hidden=True)
def resume(query: str = typer.Argument(..., help="Meeting title or ID")):
    """Show meeting notes/resume."""
    data = load_index()
    match = find_meeting(data, query)
    
    if not match:
        typer.echo(f"Meeting not found: {query}", err=True)
        raise typer.Exit(1)
    
    folder = TRANSCRIPTS_ROOT / match.get("dir")
    resume_file = folder / "resume.md"
    
    if resume_file.exists():
        typer.echo(resume_file.read_text())
    else:
        typer.echo("No resume available.", err=True)
        raise typer.Exit(1)


@app.command()
def stats():
    """Show index statistics."""
    data = load_index()
    meetings = data["meetings"]
    
    total = len(meetings)
    with_transcript = sum(1 for m in meetings if m.get("has_transcript"))
    with_resume = sum(1 for m in meetings if m.get("has_resume"))
    
    by_month = {}
    for m in meetings:
        key = f"{m.get('year')}-{m.get('month'):02d}" if m.get("year") and m.get("month") else "unknown"
        by_month[key] = by_month.get(key, 0) + 1
    
    typer.echo(f"Total meetings:    {total}")
    typer.echo(f"With transcript:   {with_transcript}")
    typer.echo(f"With resume:       {with_resume}")
    typer.echo(f"Index generated:   {data.get('generated_at', '?')}")
    typer.echo()
    typer.echo("By month:")
    for k in sorted(by_month.keys(), reverse=True)[:12]:
        typer.echo(f"  {k}: {by_month[k]}")


@app.command()
def sync(
    output_dir: Optional[str] = typer.Argument(None, help="Output directory"),
    full: bool = typer.Option(False, "--full", help="Force full sync"),
):
    """Sync meetings from Granola API."""
    from .sync import run_sync
    run_sync(output_dir or str(TRANSCRIPTS_ROOT), full=full)


@app.command()
def index():
    """Rebuild search index."""
    from .index import build_index
    build_index()


def main():
    app()


if __name__ == "__main__":
    main()
