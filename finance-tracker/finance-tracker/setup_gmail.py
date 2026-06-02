#!/usr/bin/env python3
"""
One-time Gmail OAuth setup script for Finance Tracker.
Run this before using Gmail sync:  python setup_gmail.py
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
CREDENTIALS_PATH = DATA_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"
CONFIG_PATH = DATA_DIR / "config.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def check_prerequisites():
    print("Finance Tracker - Gmail Setup")
    print("=" * 40)

    if not CREDENTIALS_PATH.exists():
        print(f"\n[ERROR] credentials.json not found at: {CREDENTIALS_PATH}")
        print("\nTo set up Gmail integration:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project (or select existing)")
        print("3. Enable the Gmail API")
        print("4. Go to 'Credentials' → 'Create Credentials' → 'OAuth 2.0 Client ID'")
        print("5. Application type: Desktop app")
        print("6. Download the JSON and save it as: data/credentials.json")
        sys.exit(1)

    print(f"[OK] credentials.json found")


def run_oauth():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("\n[ERROR] Google API libraries not installed.")
        print("Run:  pip install google-auth google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            if creds.valid:
                print("[OK] Existing token is still valid.")
                return creds
            if creds.expired and creds.refresh_token:
                print("[INFO] Refreshing expired token…")
                creds.refresh(Request())
                TOKEN_PATH.write_text(creds.to_json())
                print("[OK] Token refreshed.")
                return creds
        except Exception as e:
            print(f"[WARN] Could not load existing token: {e}")
            creds = None

    print("\n[INFO] Opening browser for Google OAuth…")
    print("(A browser window will open. Sign in with your Gmail account.)")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    print(f"[OK] Token saved to: {TOKEN_PATH}")
    return creds


def list_labels(creds):
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return []

    service = build("gmail", "v1", credentials=creds)
    result = service.users().labels().list(userId="me").execute()
    return result.get("labels", [])


def save_config(label_name: str):
    config = {"gmail_label": label_name}
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print(f"[OK] Config saved to: {CONFIG_PATH}")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    check_prerequisites()

    creds = run_oauth()

    print("\n[INFO] Fetching your Gmail labels…")
    labels = list_labels(creds)

    user_labels = [l for l in labels if l.get("type") == "user"]
    print(f"\nFound {len(user_labels)} user-created labels:")
    for i, label in enumerate(user_labels, 1):
        print(f"  {i:2}. {label['name']}")

    print("\nWhich label should Finance Tracker monitor for financial emails?")
    print("(You can create a Gmail label like 'Finance' or 'Bank Alerts')")
    print("(Press Enter to use 'Finance' as the default)")

    label_name = input("Label name: ").strip() or "Finance"

    # Check if label exists
    existing_names = {l["name"].lower() for l in labels}
    if label_name.lower() not in existing_names:
        print(f"\n[INFO] Label '{label_name}' does not exist yet.")
        print("It will be created automatically when you first sync.")
    else:
        print(f"[OK] Label '{label_name}' found in your Gmail.")

    save_config(label_name)

    print("\n" + "=" * 40)
    print("Setup complete!")
    print(f"Gmail label to monitor: {label_name}")
    print("\nNext steps:")
    print(f"1. In Gmail, label your financial emails with '{label_name}'")
    print("2. Start the Finance Tracker server:  uvicorn backend.main:app --reload")
    print("3. Click 'Sync Gmail' in the dashboard")
    print("\nTip: Set up Gmail filters to auto-label emails from your bank!")


if __name__ == "__main__":
    main()
