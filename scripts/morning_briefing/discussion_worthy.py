#!/usr/bin/env python3
"""
Fetches emails from the Gmail "Discussion Worthy" label, extracts
non-repetitive actionable insights grouped by topic, and prepends
them to DiscussionWorthy.md.
"""

import os
import sys
import json
import base64
import re
import datetime
import argparse
from pathlib import Path

import httplib2
import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google_auth_httplib2

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CONFIG_DIR = Path.home() / ".config" / "morning-briefing"
TOKEN_PATH = CONFIG_DIR / "token.json"

LABEL_NAME = "Discussion Worthy"
MAX_BODY_CHARS = 700
MAX_EMAILS = 200

NOTE_SEARCH_PATHS = [
    Path.cwd() / "DiscussionWorthy.md",
    Path.home() / "DiscussionWorthy.md",
    Path.home() / "Documents" / "DiscussionWorthy.md",
    Path.home() / "Obsidian" / "DiscussionWorthy.md",
]


# ---------------------------------------------------------------------------
# Auth (mirrors fetch_and_brief.py)
# ---------------------------------------------------------------------------

def get_google_creds() -> Credentials:
    token_env = os.environ.get("GOOGLE_TOKEN_JSON", "").strip()
    if token_env:
        creds = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)
    elif TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    else:
        creds = None

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
        return creds

    sys.exit(
        "\nERROR: No Google credentials found. Run:\n"
        "  python3 scripts/morning_briefing/setup_auth.py\n"
    )


def _authorized_http(creds):
    h = httplib2.Http(ca_certs="/etc/ssl/certs/ca-certificates.crt")
    return google_auth_httplib2.AuthorizedHttp(creds, http=h)


def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE", "")
        if token_file and Path(token_file).exists():
            api_key = Path(token_file).read_text().strip()
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs: dict = {}
    if api_key:
        if api_key.startswith("sk-ant-si"):
            kwargs["auth_token"] = api_key
        else:
            kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def _extract_body(payload: dict, max_chars: int) -> str:
    """Recursively extract plain text from a Gmail message payload."""
    mime = payload.get("mimeType", "")
    parts = payload.get("parts", [])

    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return text.strip()[:max_chars]

    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return text[:max_chars]

    # Multipart: try text/plain first, then recurse into all parts
    for part in parts:
        if part.get("mimeType") == "text/plain":
            result = _extract_body(part, max_chars)
            if result:
                return result
    for part in parts:
        result = _extract_body(part, max_chars)
        if result:
            return result

    return ""


def fetch_discussion_worthy(service) -> list[dict]:
    """Fetch all emails from the Discussion Worthy label with body content."""
    labels_result = service.users().labels().list(userId="me").execute()
    label_id = next(
        (l["id"] for l in labels_result.get("labels", [])
         if l["name"].lower() == LABEL_NAME.lower()),
        None,
    )
    if not label_id:
        sys.exit(f"\nERROR: Gmail label '{LABEL_NAME}' not found.")

    # Paginate through all messages in the label
    messages = []
    page_token = None
    while len(messages) < MAX_EMAILS:
        batch = min(100, MAX_EMAILS - len(messages))
        kwargs: dict = {"userId": "me", "labelIds": [label_id], "maxResults": batch}
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    emails = []
    total = len(messages)
    for i, meta in enumerate(messages, 1):
        print(f"  Fetching {i}/{total}...", end="\r", flush=True)
        msg = service.users().messages().get(
            userId="me", id=meta["id"], format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        body = _extract_body(msg["payload"], MAX_BODY_CHARS)
        emails.append({
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From", ""),
            "body": body,
        })

    print(f"  Fetched {total} emails.          ", flush=True)
    return emails


# ---------------------------------------------------------------------------
# Claude extraction
# ---------------------------------------------------------------------------

def extract_insights_with_claude(emails: list[dict], today: str) -> dict:
    """Returns {category: [insight, ...]} — de-duplicated and actionable."""
    client = _get_anthropic_client()

    system = (
        "You are a personal knowledge curator. "
        "Extract only directly actionable insights and things worth keeping in mind. "
        "Be ruthlessly concise — no fluff, no repetition, no fringe advice. "
        "Return strict JSON only — no prose, no markdown fences."
    )

    user = f"""Today is {today}. These {len(emails)} emails are from a personal 'Discussion Worthy' folder.

Your job: extract a clean, de-duplicated list of insights grouped by topic.

Rules:
- Only include directly actionable things to keep in mind or act on
- If multiple emails say the same thing, write it once (best version)
- Skip fringe, speculative, or highly situational advice
- Short, punchy bullets — not full paragraphs
- Use whatever category names fit (Health, Fitness, Nutrition, Finance, Relationships, Productivity, Mindset, Business, etc.)
- Only include categories that have meaningful content

Return a JSON object — no extra text:
{{
  "Health": ["point 1", "point 2"],
  "Finance": ["point 1"],
  ...
}}

EMAILS:
{json.dumps(emails, indent=2, ensure_ascii=False)}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Formatting + file I/O
# ---------------------------------------------------------------------------

def format_note(insights: dict, today: str) -> str:
    lines = [f"## Discussion Worthy — {today}", ""]
    for category, points in insights.items():
        if not points:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for point in points:
            lines.append(f"- {point}")
        lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def find_or_create_note(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path)
    for p in NOTE_SEARCH_PATHS:
        if p.exists():
            return p
    return Path.cwd() / "DiscussionWorthy.md"


def prepend_to_note(content: str, path: Path) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(content + existing, encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Discussion Worthy insights note")
    parser.add_argument("--note", metavar="PATH", help="Explicit path to DiscussionWorthy.md")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout, don't write")
    args = parser.parse_args()

    today = datetime.date.today().isoformat()

    print("Authenticating with Google...", flush=True)
    creds = get_google_creds()
    svc = build("gmail", "v1", http=_authorized_http(creds))

    print(f"Fetching '{LABEL_NAME}' emails...", flush=True)
    emails = fetch_discussion_worthy(svc)
    print(f"  {len(emails)} email(s) in label", flush=True)

    if not emails:
        print(f"No emails found in '{LABEL_NAME}' label.")
        return 0

    print("Extracting insights with Claude...", flush=True)
    insights = extract_insights_with_claude(emails, today)
    total_points = sum(len(v) for v in insights.values())
    print(f"  {total_points} insight(s) across {len(insights)} categories", flush=True)

    note = format_note(insights, today)

    if args.dry_run:
        print("\n" + "=" * 60)
        print(note)
        return 0

    path = find_or_create_note(args.note)
    prepend_to_note(note, path)
    print(f"\nInsights prepended to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
