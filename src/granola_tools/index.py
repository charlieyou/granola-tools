#!/usr/bin/env python3
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

GRANOLA_HOME = Path(os.getenv("GRANOLA_HOME", "~/.granola")).expanduser()
ROOT = GRANOLA_HOME / "transcripts"
OUT = GRANOLA_HOME / "index" / "index.json"
SCHEMA_VERSION = 1
LOCAL_TZ = os.getenv("GRANOLA_TIMEZONE", "America/New_York")


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    if not dt:
        return None
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_local(dt_utc):
    if not dt_utc:
        return None
    if ZoneInfo is None:
        return None
    try:
        tz = ZoneInfo(LOCAL_TZ)
    except Exception:
        return None
    return dt_utc.astimezone(tz)


def extract_attendees(doc):
    if not isinstance(doc, dict):
        return None
    people = doc.get("people")
    if isinstance(people, dict) and "attendees" in people:
        return people.get("attendees")
    return None


def parse_duration_json(value):
    if value is None:
        return None
    data = None
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except Exception:
            return None
    elif isinstance(value, dict):
        data = value
    else:
        return None
    duration = data.get("duration") if isinstance(data, dict) else None
    if isinstance(duration, (int, float)):
        return duration
    return None


def extract_duration(doc):
    if not isinstance(doc, dict):
        return None
    gce = doc.get("google_calendar_event")
    if not isinstance(gce, dict):
        return None
    
    # Try to calculate from start/end times
    start = gce.get("start", {})
    end = gce.get("end", {})
    start_dt = start.get("dateTime") if isinstance(start, dict) else None
    end_dt = end.get("dateTime") if isinstance(end, dict) else None
    
    if start_dt and end_dt:
        try:
            from datetime import datetime
            # Parse ISO format with timezone
            s = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))
            duration_min = int((e - s).total_seconds() / 60)
            if duration_min > 0:
                return duration_min
        except Exception:
            pass
    
    # Fallback: check extendedProperties
    ext = gce.get("extendedProperties")
    if not isinstance(ext, dict):
        return None
    for scope in ("shared", "private"):
        scope_obj = ext.get(scope)
        if not isinstance(scope_obj, dict):
            continue
        duration = parse_duration_json(scope_obj.get("meetingParams"))
        if duration is not None:
            return duration
        duration = parse_duration_json(scope_obj.get("cron.zoomMeeting"))
        if duration is not None:
            return duration
    return None


def choose_date(meta, doc):
    # Prefer google calendar event start time
    if isinstance(doc, dict):
        gce = doc.get("google_calendar_event")
        if isinstance(gce, dict):
            start = gce.get("start", {})
            if isinstance(start, dict) and start.get("dateTime"):
                return start["dateTime"]
    
    # Fallback to metadata
    if isinstance(meta, dict):
        for key in ("meeting_date", "created_at", "updated_at"):
            val = meta.get(key)
            if val:
                return val
    if isinstance(doc, dict):
        for key in ("created_at", "updated_at"):
            val = doc.get(key)
            if val:
                return val
    return None


def choose_title(meta, doc):
    if isinstance(meta, dict):
        title = meta.get("title")
        if title:
            return title
    if isinstance(doc, dict):
        title = doc.get("title")
        if title:
            return title
    return None


def choose_id(meta, doc, folder_name):
    if isinstance(meta, dict):
        val = meta.get("document_id")
        if val:
            return val
    if isinstance(doc, dict):
        val = doc.get("id")
        if val:
            return val
    return folder_name


def is_uuid_folder(name: str) -> bool:
    try:
        uuid.UUID(name)
        return True
    except Exception:
        return False


def build_index():
    if not ROOT.exists():
        raise SystemExit(f"Root not found: {ROOT}")

    meetings = []
    with os.scandir(ROOT) as it:
        for entry in it:
            if not entry.is_dir():
                continue
            if not is_uuid_folder(entry.name):
                continue
            folder = Path(entry.path)
            metadata_path = folder / "metadata.json"
            document_path = folder / "document.json"

            meta = read_json(metadata_path) if metadata_path.exists() else None
            doc = read_json(document_path) if document_path.exists() else None

            date_raw = choose_date(meta, doc)
            dt_utc = parse_dt(date_raw)
            dt_local = iso_local(dt_utc)

            full_id = choose_id(meta, doc, entry.name)
            # Generate short ID (first 7 chars of UUID, like git)
            short_id = full_id[:7] if full_id else entry.name[:7]
            
            meetings.append({
                "id": full_id,
                "short_id": short_id,
                "dir": entry.name,
                "path": str(folder),
                "transcript_path": str(folder / "transcript.md"),
                "notes_path": str(folder / "resume.md"),
                "title": choose_title(meta, doc),
                "date_utc": iso_z(dt_utc),
                "date_local": dt_local.isoformat() if dt_local else None,
                "year": dt_local.year if dt_local else None,
                "month": dt_local.month if dt_local else None,
                "date_short": dt_local.date().isoformat() if dt_local else None,
                "attendees_raw": extract_attendees(doc),
                "duration_min": extract_duration(doc),
                "has_transcript": (folder / "transcript.json").exists() or (folder / "transcript.md").exists(),
                "has_notes": (folder / "resume.md").exists(),
                "mtime": int(folder.stat().st_mtime),
            })

    meetings.sort(key=lambda m: (m.get("date_utc") or "", m.get("dir") or ""))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso_z(datetime.now(timezone.utc)),
        "root": str(ROOT),
        "meetings": meetings,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    print(f"Indexed {len(meetings)} meetings to {OUT}")


if __name__ == "__main__":
    try:
        build_index()
    except KeyboardInterrupt:
        sys.exit(130)
