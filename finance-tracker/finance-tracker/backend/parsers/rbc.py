from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .base import BaseParser


class RBCParser(BaseParser):
    """
    Parser for RBC (Royal Bank of Canada) statements.
    Handles both chequing/savings and Visa credit card statements.
    """

    bank_name = "RBC"

    @classmethod
    def detect(cls, text: str) -> bool:
        return bool(re.search(r"Royal Bank|RBC Royal Bank|rbc\.com", text, re.IGNORECASE))

    def parse(self, pdf_path: Path) -> list[dict]:
        pages = self.get_pages(pdf_path)
        full_text = "\n".join(pages)

        # Determine statement type
        if re.search(r"visa|credit card|credit account", full_text, re.IGNORECASE):
            return self._parse_credit(pdf_path, full_text)
        else:
            return self._parse_chequing(pdf_path, full_text)

    def _parse_chequing(self, pdf_path: Path, full_text: str) -> list[dict]:
        """
        RBC chequing format:
        DATE  DESCRIPTION  WITHDRAWALS  DEPOSITS  BALANCE
        e.g.: Jan 05  TIM HORTONS #123  4.50   1,234.56
        """
        transactions = []

        # Pattern: date, description, optional withdrawal, optional deposit, balance
        # Dates like "Jan 05" or "Jan 5" at start of line
        date_pattern = re.compile(
            r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}(?:\s+\d{4})?)"
            r"\s+(.+?)\s+"
            r"([\d,]+\.\d{2})?"
            r"\s*([\d,]+\.\d{2})?"
            r"\s*([\d,]+\.\d{2})?$",
            re.MULTILINE | re.IGNORECASE,
        )

        # Simpler approach: process line by line
        lines = full_text.split("\n")
        current_year = self._extract_year(full_text)

        # Skip lines that are headers or footers
        skip_patterns = re.compile(
            r"date|description|withdrawals?|deposits?|balance|opening|closing|"
            r"statement|page \d|royal bank|account number|branch|transit",
            re.IGNORECASE,
        )

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or skip_patterns.search(line):
                i += 1
                continue

            # Try to match a transaction line
            m = re.match(
                r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2})\s+"
                r"(.+?)\s+([\d,]+\.\d{2})\s*([\d,]+\.\d{2})?\s*([\d,]+\.\d{2})?$",
                line,
                re.IGNORECASE,
            )
            if m:
                raw_date, desc, col3, col4, col5 = m.groups()
                date_str = self._normalize_date(raw_date, current_year)

                # With 3 amount columns: withdrawal, deposit, balance
                # With 2 columns: could be (withdrawal, balance) or (deposit, balance)
                amount_cents = None
                account_type = "chequing"

                if col4 and col5:
                    # All three: withdrawal=col3, deposit=col4, balance=col5
                    withdrawal = self.clean_amount(col3) if col3 else 0.0
                    deposit = self.clean_amount(col4) if col4 else 0.0
                    if withdrawal > 0:
                        amount_cents = self.to_cents(withdrawal)  # positive = expense
                    else:
                        amount_cents = self.to_cents(-deposit)  # negative = income
                elif col4:
                    # Two amounts: col3 and col4
                    # Could be withdrawal + balance or deposit + balance
                    # Heuristic: if description contains "deposit" or "received", it's income
                    val3 = self.clean_amount(col3)
                    # Treat as withdrawal (expense) by default
                    amount_cents = self.to_cents(val3)
                else:
                    # Single amount
                    val3 = self.clean_amount(col3)
                    amount_cents = self.to_cents(val3)

                # Check for continuation lines (multi-line description)
                while i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not re.match(
                        r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d",
                        next_line,
                        re.IGNORECASE,
                    ) and not re.match(r"^\d{1,2}/\d{1,2}", next_line):
                        # Check if it looks like continuation text (no large numbers)
                        if not re.search(r"\d{1,3},\d{3}\.\d{2}", next_line):
                            desc = desc + " " + next_line
                            i += 1
                        else:
                            break
                    else:
                        break

                if date_str and amount_cents is not None:
                    transactions.append(
                        {
                            "date": date_str,
                            "description": desc.strip(),
                            "amount": amount_cents,
                            "account_hint": "RBC Chequing",
                            "account_type": account_type,
                            "raw_text": line,
                        }
                    )
            i += 1

        return transactions

    def _parse_credit(self, pdf_path: Path, full_text: str) -> list[dict]:
        """
        RBC Visa format:
        DATE  DESCRIPTION  AMOUNT
        Credits (payments) shown as negative or CR
        """
        transactions = []
        lines = full_text.split("\n")
        current_year = self._extract_year(full_text)

        skip_patterns = re.compile(
            r"^(date|description|amount|transaction|payments?|purchases?|"
            r"previous balance|credit limit|minimum payment|statement|page|"
            r"royal bank|account number|opening|closing|total)",
            re.IGNORECASE,
        )

        for line in lines:
            line = line.strip()
            if not line or skip_patterns.match(line):
                continue

            # Visa transaction lines: "Jan 05 Jan 07 MERCHANT NAME 12.34"
            # or "Jan 05 MERCHANT NAME 12.34 CR"
            m = re.match(
                r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2})\s+"
                r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}\s+)?"
                r"(.+?)\s+"
                r"(\([\d,]+\.\d{2}\)|[\d,]+\.\d{2})\s*(CR)?$",
                line,
                re.IGNORECASE,
            )
            if m:
                raw_date, desc, raw_amount, cr_flag = m.groups()
                date_str = self._normalize_date(raw_date, current_year)
                amount = self.clean_amount(raw_amount)

                # CR suffix or parentheses = credit/payment = negative (income/refund)
                if cr_flag or raw_amount.startswith("("):
                    amount_cents = self.to_cents(-abs(amount))
                else:
                    amount_cents = self.to_cents(amount)  # positive = charge

                if date_str:
                    transactions.append(
                        {
                            "date": date_str,
                            "description": desc.strip(),
                            "amount": amount_cents,
                            "account_hint": "RBC Visa",
                            "account_type": "credit",
                            "raw_text": line,
                        }
                    )

        return transactions

    def _extract_year(self, text: str) -> int:
        """Extract the statement year from text."""
        import datetime

        m = re.search(r"\b(20\d{2})\b", text)
        return int(m.group(1)) if m else datetime.datetime.now().year

    def _normalize_date(self, raw: str, year: int) -> Optional[str]:
        """Convert 'Jan 05' → '2024-01-05'."""
        try:
            from dateutil import parser as dp

            dt = dp.parse(f"{raw} {year}", dayfirst=False)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
