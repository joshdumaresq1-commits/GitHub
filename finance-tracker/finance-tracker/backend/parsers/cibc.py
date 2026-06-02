from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import BaseParser


class CIBCParser(BaseParser):
    """Parser for CIBC (Canadian Imperial Bank of Commerce) statements."""

    bank_name = "CIBC"

    @classmethod
    def detect(cls, text: str) -> bool:
        return bool(re.search(r"CIBC|Canadian Imperial Bank|cibc\.com", text, re.IGNORECASE))

    def parse(self, pdf_path: Path) -> list[dict]:
        full_text = self.get_text(pdf_path)
        if re.search(r"visa|mastercard|credit card|credit account", full_text, re.IGNORECASE):
            return self._parse_credit(full_text)
        return self._parse_chequing(full_text)

    def _parse_chequing(self, full_text: str) -> list[dict]:
        transactions = []
        lines = full_text.split("\n")
        year = self._extract_year(full_text)

        skip = re.compile(
            r"^(date|description|debit|credit|balance|opening|closing|"
            r"cibc|account|statement|page|branch|transit|total|canadian imperial)",
            re.IGNORECASE,
        )

        for line in lines:
            line = line.strip()
            if not line or skip.match(line):
                continue

            m = re.match(
                r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)"
                r"\s+(.+?)\s+"
                r"([\d,]+\.\d{2})?"
                r"\s*([\d,]+\.\d{2})?"
                r"\s*([\d,]+\.\d{2})?$",
                line,
                re.IGNORECASE,
            )
            if m:
                raw_date, desc, col3, col4, col5 = m.groups()
                date_str = self._normalize_date(raw_date, year)
                if not date_str:
                    continue

                debit = self.clean_amount(col3) if col3 else 0.0
                credit = self.clean_amount(col4) if col4 else 0.0

                if col5:
                    # debit, credit, balance
                    if debit > 0:
                        amount_cents = self.to_cents(debit)
                    else:
                        amount_cents = self.to_cents(-credit)
                elif col4:
                    amount_cents = self.to_cents(debit)
                else:
                    amount_cents = self.to_cents(debit)

                transactions.append(
                    {
                        "date": date_str,
                        "description": desc.strip(),
                        "amount": amount_cents,
                        "account_hint": "CIBC Chequing",
                        "account_type": "chequing",
                        "raw_text": line,
                    }
                )

        return transactions

    def _parse_credit(self, full_text: str) -> list[dict]:
        transactions = []
        lines = full_text.split("\n")
        year = self._extract_year(full_text)

        skip = re.compile(
            r"^(date|description|amount|transaction|payment|purchase|"
            r"cibc|account|statement|page|opening|closing|total|"
            r"minimum|credit limit|previous balance|canadian imperial)",
            re.IGNORECASE,
        )

        for line in lines:
            line = line.strip()
            if not line or skip.match(line):
                continue

            m = re.match(
                r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)"
                r"\s+(.+?)\s+"
                r"(\([\d,]+\.\d{2}\)|[\d,]+\.\d{2})\s*(CR|-)?$",
                line,
                re.IGNORECASE,
            )
            if m:
                raw_date, desc, raw_amount, cr_flag = m.groups()
                date_str = self._normalize_date(raw_date, year)
                if not date_str:
                    continue

                amount = self.clean_amount(raw_amount)
                if cr_flag or raw_amount.startswith("("):
                    amount_cents = self.to_cents(-abs(amount))
                else:
                    amount_cents = self.to_cents(amount)

                transactions.append(
                    {
                        "date": date_str,
                        "description": desc.strip(),
                        "amount": amount_cents,
                        "account_hint": "CIBC Credit",
                        "account_type": "credit",
                        "raw_text": line,
                    }
                )

        return transactions

    def _extract_year(self, text: str) -> int:
        import datetime
        m = re.search(r"\b(20\d{2})\b", text)
        return int(m.group(1)) if m else datetime.datetime.now().year

    def _normalize_date(self, raw: str, year: int) -> Optional[str]:
        try:
            from dateutil import parser as dp
            if "/" in raw and raw.count("/") == 2:
                dt = dp.parse(raw, dayfirst=False)
            elif "/" in raw:
                dt = dp.parse(f"{raw}/{year}", dayfirst=False)
            else:
                dt = dp.parse(f"{raw} {year}", dayfirst=False)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
