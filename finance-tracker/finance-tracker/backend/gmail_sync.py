from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
CREDENTIALS_PATH = DATA_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailSync:
    """Gmail integration for syncing financial emails."""

    def __init__(self):
        self.service = None
        self._processed_ids: set[str] = set()

    def authenticate(self) -> bool:
        """
        Run OAuth2 flow. Looks for credentials.json in data/.
        Saves token.json after first auth. Returns True on success.
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as e:
            raise ImportError(f"Google API libraries not installed: {e}")

        creds = None

        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"credentials.json not found at {CREDENTIALS_PATH}. "
                        "Download it from Google Cloud Console (OAuth 2.0 Client ID)."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
                creds = flow.run_local_server(port=0)

            TOKEN_PATH.write_text(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)
        return True

    def _ensure_authenticated(self):
        if self.service is None:
            self.authenticate()

    def get_or_create_label(self, label_name: str) -> Optional[str]:
        """Return label ID, creating it if it doesn't exist."""
        self._ensure_authenticated()
        labels_result = self.service.users().labels().list(userId="me").execute()
        for label in labels_result.get("labels", []):
            if label["name"].lower() == label_name.lower():
                return label["id"]

        # Create the label
        label_body = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = self.service.users().labels().create(userId="me", body=label_body).execute()
        return created["id"]

    def list_labels(self) -> list[dict]:
        """Return all Gmail labels."""
        self._ensure_authenticated()
        result = self.service.users().labels().list(userId="me").execute()
        return result.get("labels", [])

    def sync_label(self, label_name: str) -> list[dict]:
        """
        Fetch unprocessed emails from a Gmail label and parse financial transactions.
        Returns list of transaction dicts compatible with the parser output format.
        """
        self._ensure_authenticated()
        transactions = []

        label_id = self.get_or_create_label(label_name)
        if not label_id:
            return []

        # Get processed label id
        processed_label_id = self.get_or_create_label(f"{label_name}/processed")

        # Fetch messages with the label
        messages_result = self.service.users().messages().list(
            userId="me",
            labelIds=[label_id],
            maxResults=100,
        ).execute()

        messages = messages_result.get("messages", [])

        for msg_meta in messages:
            msg_id = msg_meta["id"]

            # Fetch full message
            msg = self.service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            # Skip already-processed messages (have the processed label)
            msg_labels = msg.get("labelIds", [])
            if processed_label_id in msg_labels:
                continue

            # Extract email content
            body = self._extract_body(msg)
            subject = self._get_header(msg, "Subject")
            sender = self._get_header(msg, "From")
            date_str = self._get_header(msg, "Date")

            # Parse financial info from email
            parsed = self._parse_financial_email(subject, body, sender, date_str, msg_id)
            transactions.extend(parsed)

            # Mark as processed by adding the processed label
            self.service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [processed_label_id]},
            ).execute()

        return transactions

    def _extract_body(self, msg: dict) -> str:
        """Extract plain text body from a Gmail message."""
        payload = msg.get("payload", {})
        return self._extract_parts(payload)

    def _extract_parts(self, payload: dict) -> str:
        mime_type = payload.get("mimeType", "")
        body = payload.get("body", {})
        data = body.get("data", "")

        if mime_type == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

        parts = payload.get("parts", [])
        for part in parts:
            result = self._extract_parts(part)
            if result:
                return result

        if mime_type == "text/html" and data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
            # Strip HTML tags
            clean = re.sub(r"<[^>]+>", " ", html)
            clean = re.sub(r"\s+", " ", clean)
            return clean

        return ""

    def _get_header(self, msg: dict, name: str) -> str:
        headers = msg.get("payload", {}).get("headers", [])
        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    def _parse_email_date(self, date_header: str) -> Optional[str]:
        """Parse email Date header to ISO date."""
        if not date_header:
            return None
        try:
            from dateutil import parser as dp
            dt = dp.parse(date_header)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    def _parse_financial_email(
        self, subject: str, body: str, sender: str, date_header: str, msg_id: str
    ) -> list[dict]:
        """
        Parse common Canadian financial emails into transaction dicts.
        Handles:
        - Interac e-Transfer received
        - Credit card transaction alerts
        - Bank balance/transaction alerts
        """
        results = []
        text = f"{subject}\n{body}"
        email_date = self._parse_email_date(date_header) or ""

        # --- Interac e-Transfer received ---
        etransfer_received = re.search(
            r"(?:has sent you|you have received).*?(?:interac|e-transfer).*?\$\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not etransfer_received:
            # Try alternate format
            etransfer_received = re.search(
                r"interac.*?e-transfer.*?received.*?\$\s*([\d,]+\.?\d*)",
                text,
                re.IGNORECASE | re.DOTALL,
            )

        if etransfer_received:
            amount_str = etransfer_received.group(1)
            amount = float(amount_str.replace(",", ""))
            # Extract sender name
            sender_match = re.search(r"from\s+([A-Z][a-zA-Z\s]+?)(?:\s+has sent|\s+sent)", text)
            sender_name = sender_match.group(1).strip() if sender_match else "Unknown Sender"
            results.append(
                {
                    "date": email_date,
                    "description": f"Interac e-Transfer Received from {sender_name}",
                    "amount": -round(amount * 100),  # negative = income
                    "account_hint": None,
                    "account_type": "chequing",
                    "source": "gmail",
                    "raw_text": f"Subject: {subject}\nMsg ID: {msg_id}",
                }
            )
            return results

        # --- Interac e-Transfer sent ---
        etransfer_sent = re.search(
            r"(?:you sent|e-transfer sent).*?\$\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if etransfer_sent:
            amount_str = etransfer_sent.group(1)
            amount = float(amount_str.replace(",", ""))
            recipient_match = re.search(r"to\s+([A-Z][a-zA-Z\s]+?)(?:\s+has been|\s+sent)", text)
            recipient = recipient_match.group(1).strip() if recipient_match else "Unknown Recipient"
            results.append(
                {
                    "date": email_date,
                    "description": f"Interac e-Transfer Sent to {recipient}",
                    "amount": round(amount * 100),  # positive = expense
                    "account_hint": None,
                    "account_type": "chequing",
                    "source": "gmail",
                    "raw_text": f"Subject: {subject}\nMsg ID: {msg_id}",
                }
            )
            return results

        # --- Credit card transaction alert ---
        # RBC MyAdvisor, Scotia alerts, etc.
        cc_alert = re.search(
            r"(?:transaction|purchase|charge).*?\$\s*([\d,]+\.?\d*).*?(?:at|from|merchant:?)\s+(.+?)(?:\.|,|\n|on )",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if cc_alert:
            amount_str = cc_alert.group(1)
            merchant = cc_alert.group(2).strip()
            amount = float(amount_str.replace(",", ""))

            # Determine account
            account_match = re.search(
                r"(?:card|account|visa|mastercard).*?ending in\s+(\d{4})", text, re.IGNORECASE
            )
            last_four = account_match.group(1) if account_match else None

            results.append(
                {
                    "date": email_date,
                    "description": merchant,
                    "amount": round(amount * 100),
                    "account_hint": f"Credit Card {last_four}" if last_four else "Credit Card",
                    "account_type": "credit",
                    "source": "gmail",
                    "raw_text": f"Subject: {subject}\nMsg ID: {msg_id}",
                }
            )
            return results

        # --- Credit card payment confirmation ---
        payment_match = re.search(
            r"payment.*?(?:of|amount:?)\s+\$\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if payment_match:
            amount_str = payment_match.group(1)
            amount = float(amount_str.replace(",", ""))
            results.append(
                {
                    "date": email_date,
                    "description": f"Credit Card Payment ({sender})",
                    "amount": -round(amount * 100),  # negative = reduces balance
                    "account_hint": None,
                    "account_type": "credit",
                    "source": "gmail",
                    "raw_text": f"Subject: {subject}\nMsg ID: {msg_id}",
                }
            )
            return results

        return results
