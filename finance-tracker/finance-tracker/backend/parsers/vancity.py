from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import BaseParser


class VancityParser(BaseParser):
    bank_name = "Vancity"

    @classmethod
    def detect(cls, text: str) -> bool:
        return bool(re.search(r"vancity|enviro.*visa|vancouver city savings", text, re.IGNORECASE))

    def parse(self, pdf_path: Path) -> list[dict]:
        pages = self.get_pages(pdf_path)
        full_text = "\n".join(pages)
        if re.search(r"credit limit|minimum payment|payment due date", full_text, re.IGNORECASE):
            return self._parse_credit(pages, full_text)
        if re.search(r"chequing|Pay As You Go", full_text, re.IGNORECASE):
            return self._parse_chequing(pages, full_text)
        return []

    def _parse_credit(self, pages: list[str], full_text: str) -> list[dict]:
        """
        Vancity Visa format:
          JAN 13 JAN 13 AUTOMATIC PAYMENT -$57.21
          DEC 23 DEC 24 WELK MART VANCOUVER BC $71.03

        Two dates (trans + post), description, dollar amount with $ prefix.
        Negative = payment/credit. Positive = charge.
        Cardholder header lines like "JOSHUA DUMARESQ: 4789..." are skipped.
        """
        transactions = []
        year = self._extract_year(full_text)
        _, end_year, start_month = self._extract_period_years(full_text)

        tx_re = re.compile(
            r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+"
            r"(.+?)\s+(-?\$[\d,]+\.\d{2})\s*$",
            re.IGNORECASE,
        )

        acct_match = re.search(r"Account Number:\s*([\d\*\s]+)", full_text)
        acct_suffix = ""
        if acct_match:
            digits = re.sub(r"[^\d]", "", acct_match.group(1))
            acct_suffix = digits[-4:] if len(digits) >= 4 else digits

        for page in pages:
            for line in page.split("\n"):
                line = line.strip()
                m = tx_re.match(line)
                if not m:
                    continue

                month_str, day_str, desc, raw_amount = m.groups()
                month_num = self._month_num(month_str)
                tx_year = end_year if month_num < start_month else (end_year - 1 if start_month > 1 else end_year)
                date_str = self._normalize_date(f"{month_str} {day_str} {tx_year}")
                if not date_str:
                    continue

                desc = desc.strip()
                neg = raw_amount.startswith("-")
                amount = float(raw_amount.lstrip("-$").replace(",", ""))
                amount_cents = self.to_cents(-amount) if neg else self.to_cents(amount)

                transactions.append({
                    "date": date_str,
                    "description": desc,
                    "amount": amount_cents,
                    "account_hint": f"Vancity Visa {acct_suffix}".strip(),
                    "account_type": "credit",
                    "source": "pdf",
                    "raw_text": line,
                })

        return transactions

    def _parse_chequing(self, pages: list[str], full_text: str) -> list[dict]:
        """
        Vancity chequing online export:
          12-May-2026 Bill payment-online VANCITY VISA -$2,205.43 $27.91
          8478
          12-May-2026 e-Transfer credit Ref $2,205.43 $2,233.34
          20260512141542812152
          JOSHUADUMARESQ

        Format: DD-Mon-YYYY description [-]$amount $balance
        Credits: positive $amount, Debits: -$amount
        Continuation lines: ref numbers, 4-digit account suffixes, ALL-CAPS names — skip them.
        """
        transactions = []

        acct_match = re.search(r"(\d{12})", full_text)
        acct_suffix = acct_match.group(1)[-4:] if acct_match else ""

        tx_re = re.compile(
            r"^(\d{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{4})\s+"
            r"(.+?)\s+(-?\$[\d,]+\.\d{2})\s+\$[\d,]+\.\d{2}\s*$",
            re.IGNORECASE,
        )
        skip_re = re.compile(
            r"^(Date\s+Description|Available funds|Relationship|Pay As You Go|Vancity GST|"
            r"\d{6,}|[A-Z]{5,}$|\d{4}$)",
        )

        all_lines: list[str] = []
        for page in pages:
            all_lines.extend(page.split("\n"))

        i = 0
        while i < len(all_lines):
            line = all_lines[i].strip()
            i += 1

            if not line or skip_re.match(line):
                continue

            m = tx_re.match(line)
            if not m:
                continue

            raw_date, desc, raw_amount = m.groups()

            # Collect short continuation lines
            while i < len(all_lines):
                next_line = all_lines[i].strip()
                if not next_line or tx_re.match(next_line) or skip_re.match(next_line):
                    break
                if re.match(r"^\d{4,}$", next_line) or re.match(r"^[A-Z]{5,}$", next_line):
                    i += 1
                    continue
                desc = desc + " " + next_line
                i += 1

            date_str = self._normalize_date(raw_date)
            if not date_str:
                continue

            neg = raw_amount.startswith("-")
            amount = float(raw_amount.lstrip("-$").replace(",", ""))
            # Debits (negative) = money out = positive cents; Credits = money in = negative cents
            amount_cents = self.to_cents(amount) if neg else self.to_cents(-amount)

            transactions.append({
                "date": date_str,
                "description": desc.strip(),
                "amount": amount_cents,
                "account_hint": f"Vancity Chequing {acct_suffix}".strip(),
                "account_type": "chequing",
                "source": "pdf",
                "raw_text": line,
            })

        return transactions

    def _extract_period_years(self, text: str):
        m = re.search(
            r"Statement period:\s*(\w+)\s+\d+\s+to\s+(\w+)\s+\d+,\s*(\d{4})",
            text, re.IGNORECASE,
        )
        if m:
            start_month_name, end_month_name, end_year = m.groups()
            start_month = self._month_num(start_month_name)
            return int(end_year), int(end_year), start_month
        year = self._extract_year(text)
        return year, year, 1

    def _extract_year(self, text: str) -> int:
        import datetime
        m = re.search(r"\b(20\d{2})\b", text)
        return int(m.group(1)) if m else datetime.datetime.now().year

    def _month_num(self, month_str: str) -> int:
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        return months.get(month_str[:3].lower(), 1)

    def _normalize_date(self, raw: str) -> Optional[str]:
        try:
            from dateutil import parser as dp
            dt = dp.parse(raw, dayfirst=False)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
