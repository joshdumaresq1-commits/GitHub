from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import BaseParser


class ScotiabankParser(BaseParser):
    bank_name = "Scotiabank"

    @classmethod
    def detect(cls, text: str) -> bool:
        return bool(re.search(r"Scotiabank|Bank of Nova Scotia|4-SCOTIA|scotiabank\.com|Ultimate Package.*\*{4}\d{4}", text, re.IGNORECASE))

    def parse(self, pdf_path: Path) -> list[dict]:
        pages = self.get_pages(pdf_path)
        full_text = "\n".join(pages)

        if re.search(r"Page created on|Current balance.*Available balance", full_text, re.IGNORECASE):
            return self._parse_online_export(pages, full_text)
        if re.search(r"credit limit|minimum payment|payment due date", full_text, re.IGNORECASE):
            return self._parse_credit(pages, full_text)
        return self._parse_chequing(pages, full_text)

    def _parse_online_export(self, pages: list[str], full_text: str) -> list[dict]:
        """
        Scotiabank online banking export format:
          Tue, Jun. 2, 2026 Mortgage Payment -$48.00 $259.11
          #5206239
          Sat, May. 30, 2026 Deposit +$1,800.00 $2,164.11
          Free Interac E-Transfer
        """
        transactions = []

        acct_match = re.search(r"\*{4}(\d{4})", full_text)
        acct_suffix = acct_match.group(1) if acct_match else ""

        tx_re = re.compile(
            r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s+(\d{1,2}),\s+(\d{4})\s+"
            r"(.+?)\s+([+-]\$[\d,]+\.\d{2})\s+\$[\d,]+\.\d{2}\s*$",
            re.IGNORECASE,
        )
        skip_re = re.compile(
            r"^(Page created|Ultimate Package|Current balance|Available balance|"
            r"Document delivery|Transactions|Filters|Current statement|Date Description|#\d+$)",
            re.IGNORECASE,
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

            month_str, day_str, year_str, desc, raw_amount = m.groups()

            # Collect continuation lines
            while i < len(all_lines):
                next_line = all_lines[i].strip()
                if not next_line or skip_re.match(next_line) or tx_re.match(next_line):
                    break
                if re.match(r"^#\d+$", next_line):
                    i += 1
                    break
                desc = desc + " " + next_line
                i += 1

            date_str = self._normalize_date(f"{month_str} {day_str} {year_str}", int(year_str))
            if not date_str:
                continue

            neg = raw_amount.startswith("-")
            amount = float(raw_amount.lstrip("+-$").replace(",", ""))
            amount_cents = self.to_cents(amount) if neg else self.to_cents(-amount)

            transactions.append({
                "date": date_str,
                "description": desc.strip(),
                "amount": amount_cents,
                "account_hint": f"Scotia Chequing {acct_suffix}".strip(),
                "account_type": "chequing",
                "source": "pdf",
                "raw_text": line,
            })

        return transactions

    def _parse_chequing(self, pages: list[str], full_text: str) -> list[dict]:
        """
        Scotiabank chequing PDF format (actual observed format):
          Apr1 Deposit 10,000.00 10,298.39
          73559875FreeInteracE-Transfer        <- continuation line
          Apr1 MB-Transferto 10,000.00 298.39
          CreditCard                           <- continuation line

        Two amounts per line: transaction_amount  new_balance
        Direction determined by whether balance went up (deposit) or down (withdrawal).
        """
        transactions = []
        year = self._extract_year(full_text)

        acct_match = re.search(r"(\d{9,})", full_text)
        acct_suffix = acct_match.group(1)[-4:] if acct_match else ""

        # Transaction line: Month+Day, description, amount, balance
        tx_re = re.compile(
            r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*(\d{1,2})\s+"
            r"(.+?)\s+"
            r"([\d,]+\.\d{2})\s+"
            r"([\d,]+\.\d{2})\s*$",
            re.IGNORECASE,
        )

        skip_re = re.compile(
            r"^(Amounts\s+Amounts|withdrawn|deposited|Balance\(\$\)|Page\s*\d|Here|continued|"
            r"-{3,}|\|$|\d{6,}$|[A-Z0-9_]{10,}$)",
            re.IGNORECASE,
        )

        # Extract opening balance for direction tracking
        prev_balance: Optional[float] = None
        ob_match = re.search(r"OpeningBalance\S*\s+\$?([\d,]+\.\d{2})", full_text)
        if ob_match:
            prev_balance = float(ob_match.group(1).replace(",", ""))

        all_lines: list[str] = []
        for page_text in pages:
            all_lines.extend(page_text.split("\n"))

        i = 0
        while i < len(all_lines):
            line = all_lines[i].strip()
            i += 1

            if not line or skip_re.match(line):
                continue

            m = tx_re.match(line)
            if not m:
                continue

            month, day, desc, amount_str, balance_str = m.groups()
            date_str = self._normalize_date(f"{month} {day}", year)
            if not date_str:
                continue

            amount = float(amount_str.replace(",", ""))
            balance = float(balance_str.replace(",", ""))

            # Collect continuation description lines (extra merchant detail on next line)
            while i < len(all_lines):
                next_line = all_lines[i].strip()
                is_new_tx = tx_re.match(next_line)
                is_month_start = re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d", next_line, re.IGNORECASE)
                is_structural = re.match(r"^(Date\s|Amounts|Here|Page\s*\d|continued|Closing|Opening|-{3,}|\|$)", next_line, re.IGNORECASE)
                is_junk = re.match(r"^(\d{6,}|[A-Z0-9_]{15,}|\*\d|\d+-\d+)$", next_line, re.IGNORECASE)
                if next_line and not is_new_tx and not is_month_start and not is_structural and not is_junk:
                    desc = desc + " " + next_line
                    i += 1
                else:
                    break

            # Skip summary lines
            if re.search(r"OpeningBalance|ClosingBalance", desc, re.IGNORECASE):
                prev_balance = balance
                continue

            # Determine direction from balance movement
            if prev_balance is not None:
                is_deposit = balance > prev_balance
            else:
                is_deposit = bool(re.search(r"deposit|received|credit|refund|e-transfer", desc, re.IGNORECASE))

            prev_balance = balance

            amount_cents = self.to_cents(-amount) if is_deposit else self.to_cents(amount)

            transactions.append({
                "date": date_str,
                "description": desc.strip(),
                "amount": amount_cents,
                "account_hint": f"Scotia Chequing {acct_suffix}".strip(),
                "account_type": "chequing",
                "source": "pdf",
                "raw_text": line,
            })

        return transactions

    def _parse_credit(self, pages: list[str], full_text: str) -> list[dict]:
        """
        Handles two formats:
        1. Scotiabank Gold Amex: 001 May 15 May 17 DESCRIPTION 8.07
        2. Generic Scotiabank credit: Jan 15 DESCRIPTION 8.07
        """
        year = self._extract_year(full_text)

        # Check for Amex-style numbered transactions
        if re.search(r"^\d{3}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}", full_text, re.IGNORECASE | re.MULTILINE):
            return self._parse_amex_credit(pages, full_text, year)

        transactions = []
        lines = full_text.split("\n")

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

                transactions.append({
                    "date": date_str,
                    "description": desc.strip(),
                    "amount": amount_cents,
                    "account_hint": "Scotiabank Credit",
                    "account_type": "credit",
                    "source": "pdf",
                    "raw_text": line,
                })

        return transactions

    def _parse_amex_credit(self, pages: list[str], full_text: str, year: int) -> list[dict]:
        """
        Scotiabank Gold Amex format:
          001 May 15 May 17 HYBAR NATURALLY 001 VANCOUVER BC 8.07
          013 May 18 May 21 SAFEWAY #4941 VANCOUVER VANCOUVER 64.10
          BC                                          <- continuation
        Ref# trans-date post-date description amount
        Credits show as negative amounts.
        """
        transactions = []

        acct_match = re.search(r"Account#\s*([\dXx\s]+)", full_text)
        acct_suffix = ""
        if acct_match:
            digits = re.sub(r"[^\d]", "", acct_match.group(1))
            acct_suffix = digits[-4:] if len(digits) >= 4 else digits

        tx_re = re.compile(
            r"^\d{3}\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+"
            r"(.+?)\s+(-?[\d,]+\.\d{2})\s*$",
            re.IGNORECASE,
        )
        skip_re = re.compile(
            r"^(TRANS\.|REF\.|SUB-TOTAL|Interest charges|Cash advances|Purchases|"
            r"Special|Statement|Account#|Page\s*\d|Scotiabank|American Express|"
            r"MR\s|MRS\s|Continued|Please|ACCOUNT#|As you)",
            re.IGNORECASE,
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

            month_str, day_str, desc, raw_amount = m.groups()
            date_str = self._normalize_date(f"{month_str} {day_str}", year)
            if not date_str:
                continue

            # Collect short continuation lines (e.g. "BC" wrapping)
            while i < len(all_lines):
                next_line = all_lines[i].strip()
                if not next_line or tx_re.match(next_line) or skip_re.match(next_line) or len(next_line) > 40:
                    break
                if re.match(r"^\d{3}\s", next_line):
                    break
                desc = desc + " " + next_line
                i += 1

            neg = raw_amount.startswith("-")
            amount = float(raw_amount.lstrip("-").replace(",", ""))
            amount_cents = self.to_cents(-amount) if neg else self.to_cents(amount)

            transactions.append({
                "date": date_str,
                "description": desc.strip(),
                "amount": amount_cents,
                "account_hint": f"Scotia Amex {acct_suffix}".strip(),
                "account_type": "credit",
                "source": "pdf",
                "raw_text": line,
            })

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
