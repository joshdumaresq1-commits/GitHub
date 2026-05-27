#!/usr/bin/env python3
"""
One-time Google OAuth setup for the morning briefing skill.

Steps:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or pick an existing one).
  3. Enable Gmail API and Google Calendar API.
  4. Create OAuth 2.0 credentials (Desktop App type).
  5. Download the JSON file and save it to ~/.config/morning-briefing/credentials.json
  6. Run this script: python3 scripts/morning_briefing/setup_auth.py

The script will open your browser, ask you to authorize access,
then save a token to ~/.config/morning-briefing/token.json for future runs.
"""

import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "morning-briefing"
TOKEN_PATH = CONFIG_DIR / "token.json"
CREDS_PATH = CONFIG_DIR / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit(
            "Missing dependencies. Install them first:\n"
            "  pip install -r scripts/morning_briefing/requirements.txt\n"
        )

    if not CREDS_PATH.exists():
        print(f"credentials.json not found at {CREDS_PATH}\n")
        print("To get it:")
        print("  1. Visit https://console.cloud.google.com/")
        print("  2. Create/select a project.")
        print("  3. Enable Gmail API and Google Calendar API.")
        print("  4. APIs & Services > Credentials > Create OAuth 2.0 Client ID")
        print("     Application type: Desktop App")
        print("  5. Download the JSON and save to:")
        print(f"     {CREDS_PATH}")
        print("\nThen re-run this script.")
        sys.exit(1)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    print("Opening browser for Google authorization...")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json())
    print(f"\nAuthorization complete. Token saved to {TOKEN_PATH}")
    print("You can now run the morning briefing:\n")
    print("  python3 scripts/morning_briefing/fetch_and_brief.py")
    print("  # or via Claude Code:")
    print("  /morning-briefing")


if __name__ == "__main__":
    main()
