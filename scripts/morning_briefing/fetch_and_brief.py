#!/usr/bin/env python3
"""
Fetches Gmail inbox + Google Calendar, prioritizes tasks via Claude,
and prepends a structured briefing to MonoNote.md.
"""

import os
import sys
import json
import base64
import datetime
import argparse
import re
from pathlib import Path

import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

CONFIG_DIR = Path.home() / ".config" / "morning-briefing"
TOKEN_PATH = CONFIG_DIR / "token.json"
CREDS_PATH = CONFIG_DIR / "credentials.json"

MONONOTE_SEARCH_PATHS = [
    Path.cwd() / "MonoNote.md",
    Path.home() / "MonoNote.md",
    Path.home() / "Documents" / "MonoNote.md",
    Path.home() / "Obsidian" / "MonoNote.md",
]


# ---------------------------------------------------------------------------
# Google auth
# ---------------------------------------------------------------------------

def get_google_creds():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_PATH.exists():
                sys.exit(
                    f"\nERROR: credentials.json not found at {CREDS_PATH}\n"
                    "Run setup first:\n"
                    "  python3 scripts/morning_briefing/setup_auth.py\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
    return creds


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def decode_snippet(snippet: str) -> str:
    return snippet.replace("&#39;", "'").replace("&quot;", '"').replace("&amp;", "&")


def fetch_gmail_inbox(service, max_results: int = 60) -> list[dict]:
    """
    Returns all emails sitting in the unsorted primary inbox.
    Excludes Promotions / Social / Updates / Forums categories.
    Includes unread AND read emails that are still in INBOX (action-pending).
    """
    result = service.users().messages().list(
        userId="me",
        labelIds=["INBOX"],
        q="-category:promotions -category:social -category:updates -category:forums",
        maxResults=max_results,
    ).execute()

    emails = []
    for meta in result.get("messages", []):
        msg = service.users().messages().get(
            userId="me",
            id=meta["id"],
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        emails.append(
            {
                "id": meta["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": decode_snippet(msg.get("snippet", "")),
                "unread": "UNREAD" in msg.get("labelIds", []),
            }
        )
    return emails


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

def fetch_calendar_events(service) -> list[dict]:
    """Returns today's calendar events (local midnight → +24 h)."""
    local_now = datetime.datetime.now(datetime.timezone.utc)
    start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + datetime.timedelta(days=1)

    result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for e in result.get("items", []):
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        events.append(
            {
                "summary": e.get("summary", "(no title)"),
                "start": start,
                "description": e.get("description", "")[:300],
                "location": e.get("location", ""),
                "attendees": len(e.get("attendees", [])),
            }
        )
    return events


# ---------------------------------------------------------------------------
# Claude prioritization
# ---------------------------------------------------------------------------

def prioritize_with_claude(emails: list[dict], events: list[dict], today: str) -> list[dict]:
    """
    Calls Claude to extract action items and rank them HIGH / MEDIUM / LOW.
    Returns a list of task dicts sorted high → low.
    """
    client = anthropic.Anthropic()

    system = (
        "You are a personal productivity assistant. "
        "Analyze emails and calendar events, extract only concrete action items, "
        "and prioritize them. Return strict JSON — no prose, no markdown fence."
    )

    user = f"""Today is {today}.

INBOX EMAILS (unsorted primary inbox, may include older dates):
{json.dumps(emails, indent=2, ensure_ascii=False)}

TODAY'S CALENDAR EVENTS:
{json.dumps(events, indent=2, ensure_ascii=False)}

Rules:
- Only include items that require a human action or decision.
- Calendar events count as tasks only if they need prep, a reply, or represent a commitment.
- Emails that are purely FYI with no needed response should be omitted.
- Older emails that are still unarchived imply they need attention — include them.
- Priority rubric:
    HIGH   = deadline today/tomorrow, waiting on you, meeting prep needed, financial/legal/urgent
    MEDIUM = needs a response soon (this week), meeting in next few days, follow-up needed
    LOW    = can wait, informational but needs acknowledgement, low-stakes

Return a JSON array, sorted HIGH first, then MEDIUM, then LOW:
[
  {{
    "priority": "HIGH" | "MEDIUM" | "LOW",
    "title": "concise imperative action (max 80 chars)",
    "source_type": "email" | "calendar",
    "source_detail": "subject or event name + sender/organizer if email",
    "due_hint": "today | this week | whenever | <specific date if stated>"
  }}
]"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    raw = response.content[0].text.strip()
    # Strip accidental markdown code fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# MonoNote formatting
# ---------------------------------------------------------------------------

def format_briefing(tasks: list[dict], today: str) -> str:
    lines = [
        f"## {today}",
        "",
        "### Morning Briefing",
        "",
    ]

    sections = [
        ("HIGH",   "High Priority"),
        ("MEDIUM", "Medium Priority"),
        ("LOW",    "Low Priority"),
    ]

    for level, label in sections:
        level_tasks = [t for t in tasks if t["priority"] == level]
        if not level_tasks:
            continue
        lines.append(f"#### {label}")
        lines.append("")
        for task in level_tasks:
            lines.append(f"- [ ] {task['title']}")
            lines.append(f"  - Source: {task['source_type'].capitalize()} — {task['source_detail']}")
            if task.get("due_hint"):
                lines.append(f"  - Due: {task['due_hint']}")
            lines.append(f"  - Priority:   [ ] High  [ ] Medium  [ ] Low")
            lines.append(f"  - Relevance:  [ ] Relevant  [ ] Skip")
            lines.append(f"  - Status:     [ ] Done  [ ] Bump  [ ] Cancelled")
            lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def find_or_create_mononote(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path)
    for p in MONONOTE_SEARCH_PATHS:
        if p.exists():
            return p
    # Default: create next to cwd
    return Path.cwd() / "MonoNote.md"


def prepend_to_mononote(content: str, path: Path) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(content + existing, encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Morning briefing for MonoNote.md")
    parser.add_argument(
        "--mononote", metavar="PATH",
        help="Explicit path to MonoNote.md (auto-detected if omitted)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the briefing to stdout instead of writing to MonoNote.md",
    )
    args = parser.parse_args()

    today = datetime.date.today().isoformat()

    print("Authenticating with Google...", flush=True)
    creds = get_google_creds()

    gmail_svc = build("gmail", "v1", credentials=creds)
    cal_svc = build("calendar", "v3", credentials=creds)

    print("Fetching Gmail inbox...", flush=True)
    emails = fetch_gmail_inbox(gmail_svc)
    print(f"  {len(emails)} email(s) in primary inbox", flush=True)

    print("Fetching today's calendar events...", flush=True)
    events = fetch_calendar_events(cal_svc)
    print(f"  {len(events)} event(s) today", flush=True)

    if not emails and not events:
        print("Nothing to prioritize — inbox empty and no events today.")
        return 0

    print("Prioritizing with Claude...", flush=True)
    tasks = prioritize_with_claude(emails, events, today)
    print(f"  {len(tasks)} action item(s) identified", flush=True)

    briefing = format_briefing(tasks, today)

    if args.dry_run:
        print("\n" + "=" * 60)
        print(briefing)
        return 0

    mononote = find_or_create_mononote(args.mononote)
    prepend_to_mononote(briefing, mononote)
    print(f"\nBriefing prepended to {mononote}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
