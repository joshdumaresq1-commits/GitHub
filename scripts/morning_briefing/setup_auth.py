#!/usr/bin/env python3
"""
One-time Google OAuth setup for the morning briefing skill.

Works in both local terminals and web/cloud environments (Claude Code on the web).

HOW TO GET credentials.json:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or pick an existing one).
  3. Enable Gmail API and Google Calendar API.
  4. APIs & Services > Credentials > Create Credentials > OAuth 2.0 Client ID
     Application type: Desktop App
  5. Download the JSON file.

Then either:
  A) Save it to ~/.config/morning-briefing/credentials.json  (local/file approach)
  B) Set its contents as the GOOGLE_CREDENTIALS_JSON env var  (web/cloud approach)

Run this script once. It will:
  - Print a URL — open it in your browser and authorize access.
  - Ask you to paste back the authorization code.
  - Save the token and print its JSON so you can set GOOGLE_TOKEN_JSON.
"""

import os
import sys
import json
import tempfile
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "morning-briefing"
TOKEN_PATH = CONFIG_DIR / "token.json"
CREDS_PATH = CONFIG_DIR / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


REDIRECT_URI = "http://localhost"


def build_flow(creds_file):
    from google_auth_oauthlib.flow import InstalledAppFlow
    return InstalledAppFlow.from_client_secrets_file(
        creds_file,
        SCOPES,
        redirect_uri=REDIRECT_URI,
    )


def resolve_creds_file():
    creds_env = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if creds_env:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_env)
        tmp.close()
        print("Using credentials from GOOGLE_CREDENTIALS_JSON env var.")
        return tmp.name
    if CREDS_PATH.exists():
        print(f"Using credentials from {CREDS_PATH}")
        return str(CREDS_PATH)
    print("No credentials found.\n")
    print("Option A — File (local use):")
    print(f"  Save your credentials JSON to: {CREDS_PATH}")
    print()
    print("Option B — Environment variable (web/cloud use):")
    print("  Set GOOGLE_CREDENTIALS_JSON to the full contents of the downloaded JSON.")
    print("  In Claude Code on the web: Environment settings > Add variable.")
    print()
    print("To get credentials.json:")
    print("  1. https://console.cloud.google.com/")
    print("  2. Enable Gmail API + Google Calendar API")
    print("  3. APIs & Services > Credentials > OAuth 2.0 Client ID (Desktop App)")
    print("  4. Download JSON")
    sys.exit(1)


def print_token(creds):
    print(f"\nToken saved to {TOKEN_PATH}")
    print()
    print("=" * 70)
    print("IMPORTANT — Web/cloud users: copy everything between the lines below")
    print("and save it as the GOOGLE_TOKEN_JSON environment variable in your")
    print("Claude Code web environment settings. This lets the token survive")
    print("across sessions (since the container resets each time).")
    print("=" * 70)
    print(creds.to_json())
    print("=" * 70)
    print()
    print("Setup complete. You can now run /morning-briefing")


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
    except ImportError:
        sys.exit(
            "Missing dependencies. Install them first:\n"
            "  pip install -r scripts/morning_briefing/requirements.txt\n"
        )

    # When called with a code argument, exchange it for a token.
    if len(sys.argv) == 3 and sys.argv[1] == "--exchange":
        code = sys.argv[2]
        creds_file = resolve_creds_file()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        flow = build_flow(creds_file)
        flow.fetch_token(code=code)
        creds = flow.credentials
        TOKEN_PATH.write_text(creds.to_json())
        print_token(creds)
        return

    # Default: print the authorization URL.
    creds_file = resolve_creds_file()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    flow = build_flow(creds_file)
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    print()
    print("Open this URL in your browser:\n")
    print(auth_url)
    print()
    print("After authorizing, your browser will redirect to http://localhost/...")
    print("That page won't load — that's expected.")
    print("Copy the 'code' value from the URL bar and paste it back here.")


if __name__ == "__main__":
    main()
