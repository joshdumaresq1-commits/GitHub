from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import BaseParser


class AmexParser(BaseParser):
    """
    Parser for American Express statements.
    Amex statements: Date, Description, Amount
    Credits (payments/refunds) shown as negative amounts.
    """

    bank_name = "Amex"

    @classmethod
    def detect(cls, text: str) -> bool:
        return bool(re.search(r"American Express|Amex|americanexpress\.com", text, re.IGNORECASE))

    def parse(self, pdf_path: Path) -> list[dict]:
        full_text = self.get_text(pdf_path)
        return self._parse_statement(full_text)

    def _parse_statement(self, full_text: str) -> list[dict]:
        """
        Amex statement format:
        Date  Description  Amount
        Charges are positive, credits/payments are negative or show as -$123.45
        """
        transactions = []
        lines = full_text.split("\n")
        year = self._extract_year(full_text)

        skip = re.compile(
            r"^(date|description|amount|transaction|payment|purchase|"
            r"american express|amex|account|statement|page|opening|closing|total|"
            r"minimum|credit limit|previous balance|new balance|"
            r"points|rewards|membership)",
            re.IGNORECASE,
        )

        for line in lines:
            line = line.strip()
            if not line or skip.match(line):
                continue

            # Amex date format: "Jan 05" or "01/05/24" or "2024-01-05"
            # Amount can be negative: -123.45 or (123.45)
            m = re.match(
                r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2})"
                r"\s+(.+?)\s+"
                r"(-?[\d,]+\.\d{2}|\([\d,]+\.\d{2}\))$",
                line,
                re.IGNORECASE,
            )
            if m:
                raw_date, desc, raw_amount = m.groups()
                date_str = self._normalize_date(raw_date, year)
                if not date_str:
                    continue

                amount = self.clean_amount(raw_amount)
                # On Amex: negative = credit/payment, positive = charge
                amount_cents = self.to_cents(amount)

                transactions.append(
                    {
                        "date": date_str,
                        "description": desc.strip(),
                        "amount": amount_cents,
                        "account_hint": "Amex Credit",
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
            if re.match(r"\d{4}-\d{2}-\d{2}", raw):
                return raw
            elif "/" in raw and raw.count("/") == 2:
                dt = dp.parse(raw, dayfirst=False)
            elif "/" in raw:
                dt = dp.parse(f"{raw}/{year}", dayfirst=False)
            else:
                dt = dp.parse(f"{raw} {year}", dayfirst=False)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
