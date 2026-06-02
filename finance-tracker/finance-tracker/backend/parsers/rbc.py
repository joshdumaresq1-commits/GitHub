from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import BaseParser


class RBCParser(BaseParser):
    bank_name = "RBC"

    @classmethod
    def detect(cls, text: str) -> bool:
        return bool(re.search(r"Royal Bank|RBC Royal Bank|rbcroyalbank\.com|rbc\.com", text, re.IGNORECASE))

    def parse(self, pdf_path: Path) -> list[dict]:
        pages = self.get_pages(pdf_path)
        full_text = "\n".join(pages)
        if re.search(r"visa|credit card|credit account", full_text, re.IGNORECASE):
            return self._parse_credit(pages, full_text)
        return self._parse_chequing(pages, full_text)

    def _parse_chequing(self, pages: list[str], full_text: str) -> list[dict]:
        """
        RBC chequing actual format (observed):
          10Dec e-Transfersent babysitter-alex
          ZJW3B6 60.00 1,985.47
          15Dec OnlineBankingtransfer-8474 4,000.00 5,985.47
          PayrollDeposit ANTHEMPROPERTI 3,871.27
          OnlineBankingpayment-5861
          VISAROYALBNK 3,334.00

        Date: DDMon (no space, no year)
        Amounts: line ends with one or two decimals (amount, optional balance)
        Multi-line: description on one line, ref+amounts on next
        Multiple transactions can share a date
        """
        start_year, end_year, start_month = self._extract_period_years(full_text)
        acct_match = re.search(r"(\d{5}-\d{7})", full_text)
        acct_suffix = acct_match.group(1)[-4:] if acct_match else ""

        # Date: 10Dec, 2Jan, 15Dec (no space between day and month)
        date_re = re.compile(
            r"^(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*",
            re.IGNORECASE,
        )
        # Amounts at end of line: "60.00 1,985.47" or "3,871.27" or "1,439.93 -545.43"
        amount_re = re.compile(r"^(.*?)\s+([\d,]+\.\d{2})(?:\s+([-]?[\d,]+\.\d{2}))?\s*$")

        skip_re = re.compile(
            r"^(Date\s+Desc|Opening|Closing|Details|Summary|Important|Protect|Never|Cover|"
            r"Here\s|Stay\s|Please\s|TM\s|®|https?://|From\s|Your\s+RBC|RBC\s*Private|"
            r"Royal\s*Bank|P\.O\.|Calgary|How\s*to|www\.|GST\s*Reg|Trademark|Registered|"
            r"\d+of\d+|\*\d+\*)",
            re.IGNORECASE,
        )
        junk_re = re.compile(r"^[\d\-\*\s]+$|^[A-Z0-9_\-]{25,}$", re.IGNORECASE)

        all_lines: list[str] = []
        for page in pages:
            all_lines.extend(page.split("\n"))

        prev_balance: Optional[float] = None
        ob = re.search(r"openingbalance\S*\s+\$?([\d,]+\.\d{2})", full_text, re.IGNORECASE)
        if ob:
            prev_balance = float(ob.group(1).replace(",", ""))

        transactions = []
        current_date: Optional[str] = None
        desc_parts: list[str] = []

        for line in all_lines:
            line = line.strip()
            if not line or skip_re.match(line) or junk_re.match(line):
                continue

            # Strip date prefix if present
            dm = date_re.match(line)
            if dm:
                month_num = self._month_num(dm.group(2))
                year = end_year if month_num < start_month else start_year
                current_date = self._normalize_date(f"{dm.group(1)} {dm.group(2)} {year}")
                line = line[dm.end():].strip()

            if not line:
                continue

            # Try to match amounts at end of line
            am = amount_re.match(line)
            if am:
                desc_part, amount_str, balance_str = am.group(1).strip(), am.group(2), am.group(3)

                # Skip pure reference codes with no real description
                full_desc = " ".join(desc_parts + ([desc_part] if desc_part else [])).strip()
                desc_parts = []

                if not full_desc or not current_date:
                    continue

                # Skip junk
                if junk_re.match(full_desc) or re.match(r"^[\d\-]+$", full_desc):
                    continue

                amount = float(amount_str.replace(",", ""))
                balance = float(balance_str.replace(",", "")) if balance_str else None

                # Determine direction
                if balance is not None and prev_balance is not None:
                    is_deposit = balance > prev_balance
                else:
                    is_deposit = bool(re.search(
                        r"payroll|deposit|received|e-transfer.*rec|mobile.*deposit|credit",
                        full_desc, re.IGNORECASE,
                    ))

                if balance is not None:
                    prev_balance = balance

                if re.search(r"opening|closing", full_desc, re.IGNORECASE):
                    continue

                amount_cents = self.to_cents(-amount) if is_deposit else self.to_cents(amount)

                transactions.append({
                    "date": current_date,
                    "description": full_desc,
                    "amount": amount_cents,
                    "account_hint": f"RBC Chequing {acct_suffix}".strip(),
                    "account_type": "chequing",
                    "source": "pdf",
                    "raw_text": line,
                })
            else:
                # No amounts — accumulate as description
                if not junk_re.match(line) and not re.match(r"^[\d\-]+$", line):
                    desc_parts.append(line)

        return transactions

    def _parse_credit(self, pages: list[str], full_text: str) -> list[dict]:
        transactions = []
        year = self._extract_year(full_text)
        lines = full_text.split("\n")

        skip = re.compile(
            r"^(date|description|amount|transaction|payment|purchase|"
            r"royal bank|rbc|account|statement|page|opening|closing|total|"
            r"minimum|credit limit|previous balance|new balance)",
            re.IGNORECASE,
        )

        for line in lines:
            line = line.strip()
            if not line or skip.match(line):
                continue

            m = re.match(
                r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)"
                r"\s+(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}\s+)?"
                r"(.+?)\s+"
                r"(\([\d,]+\.\d{2}\)|[\d,]+\.\d{2})\s*(CR)?$",
                line, re.IGNORECASE,
            )
            if m:
                raw_date, desc, raw_amount, cr_flag = m.groups()
                date_str = self._normalize_date(f"{raw_date} {year}")
                if not date_str:
                    continue
                amount = self.clean_amount(raw_amount)
                if cr_flag or raw_amount.startswith("("):
                    amount_cents = self.to_cents(-abs(amount))
                else:
                    amount_cents = self.to_cents(amount)

                transactions.append({
                    "date": date_str,
                    "description": desc.strip(),
                    "amount": amount_cents,
                    "account_hint": "RBC Visa",
                    "account_type": "credit",
                    "source": "pdf",
                    "raw_text": line,
                })

        return transactions

    def _extract_period_years(self, text: str):
        """Extract start year, end year, and start month number from statement period."""
        import datetime
        m = re.search(
            r"From\w*\s*(January|February|March|April|May|June|July|August|September|October|November|December)\w*\s*\d+,?\s*(\d{4})\w*\s*to\w*\s*(January|February|March|April|May|June|July|August|September|October|November|December)\w*\s*\d+,?\s*(\d{4})",
            text, re.IGNORECASE,
        )
        if m:
            start_month_name, start_year, end_month_name, end_year = m.groups()
            start_month = self._month_num(start_month_name)
            return int(start_year), int(end_year), start_month
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
            dt = dp.parse(raw, dayfirst=True)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
