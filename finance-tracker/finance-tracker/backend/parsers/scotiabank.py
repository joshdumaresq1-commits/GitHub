from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import BaseParser


class ScotiabankParser(BaseParser):
    """
    Parser for Scotiabank (The Bank of Nova Scotia) statements.
    Handles chequing and credit card statements.
    """

    bank_name = "Scotiabank"

    @classmethod
    def detect(cls, text: str) -> bool:
        return bool(re.search(r"Scotiabank|Bank of Nova Scotia|scotia\.com", text, re.IGNORECASE))

    def parse(self, pdf_path: Path) -> list[dict]:
        full_text = self.get_text(pdf_path)

        if re.search(r"visa|mastercard|credit card|credit account", full_text, re.IGNORECASE):
            return self._parse_credit(full_text)
        return self._parse_chequing(full_text)

    def _parse_chequing(self, full_text: str) -> list[dict]:
        """
        Scotiabank chequing:
        Date  Description  Withdrawals  Deposits  Balance
        """
        transactions = []
        lines = full_text.split("\n")
        year = self._extract_year(full_text)

        skip = re.compile(
            r"^(date|description|withdrawal|deposit|balance|opening|closing|"
            r"scotiabank|account|statement|page|branch|transit|total)",
            re.IGNORECASE,
        )

        for line in lines:
            line = line.strip()
            if not line or skip.match(line):
                continue

            # Date formats: Jan 05, Jan. 05, 01/05
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

                withdrawal = self.clean_amount(col3) if col3 else 0.0
                deposit = self.clean_amount(col4) if col4 else 0.0

                if col5:
                    # Three amount columns: withdrawal, deposit, balance
                    if withdrawal > 0:
                        amount_cents = self.to_cents(withdrawal)
                    else:
                        amount_cents = self.to_cents(-deposit)
                elif col4:
                    # Two columns: ambiguous; check desc for deposit keywords
                    if re.search(r"deposit|received|payroll|credit", desc, re.IGNORECASE):
                        amount_cents = self.to_cents(-withdrawal)  # it was actually a deposit
                    else:
                        amount_cents = self.to_cents(withdrawal)
                else:
                    amount_cents = self.to_cents(withdrawal)

                transactions.append(
                    {
                        "date": date_str,
                        "description": desc.strip(),
                        "amount": amount_cents,
                        "account_hint": "Scotiabank Chequing",
                        "account_type": "chequing",
                        "raw_text": line,
                    }
                )

        return transactions

    def _parse_credit(self, full_text: str) -> list[dict]:
        """
        Scotiabank credit card:
        Date  Description  Amount (credits shown with CR or negative)
        """
        transactions = []
        lines = full_text.split("\n")
        year = self._extract_year(full_text)

        skip = re.compile(
            r"^(date|description|amount|transaction|payment|purchase|"
            r"scotiabank|account|statement|page|opening|closing|total|"
            r"minimum|credit limit|previous balance)",
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
                        "account_hint": "Scotiabank Credit",
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
