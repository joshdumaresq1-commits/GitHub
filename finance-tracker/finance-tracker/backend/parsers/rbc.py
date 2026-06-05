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
        if re.search(r"Pending Transactions|Posted Transactions|Current Balance.*Pending.*Available Credit", full_text, re.IGNORECASE):
            return self._parse_online_credit(pages, full_text)
        if re.search(r"credit limit|minimum payment|payment due date|credit card statement", full_text, re.IGNORECASE):
            return self._parse_credit(pages, full_text)
        return self._parse_chequing(pages, full_text)

    def _parse_online_credit(self, pages: list[str], full_text: str) -> list[dict]:
        """
        RBC Visa online banking export format:
          Jun 2, 2026 RBC GRANFONDO WHISTLER, VANCOUVER $108.31
          May 24, 2026 BCF-CUSTOMER SERVICE CENT, VICTORIA -$51.45
          May 12, 2026 PAYMENT - THANK YOU / PAIEMENT - MERCI -$5,097.70

        Single date, description with optional city, dollar amount (negative = credit/payment).
        Includes both pending and posted transactions.
        """
        transactions = []

        acct_match = re.search(r"(\d{4})\s+\*+\s+\*+\s+(\d{4})", full_text)
        acct_suffix = acct_match.group(2) if acct_match else ""

        tx_re = re.compile(
            r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})\s+"
            r"(.+?)\s+(-?\$[\d,]+\.\d{2})\s*$",
            re.IGNORECASE,
        )
        skip_re = re.compile(
            r"^(Pending Transactions|Posted Transactions|Date Description|"
            r"Royal Bank|RBC Avion|Foreign Currency|Avion Rewards|"
            r"Current Balance|Statement balance|Minimum payment|Payment due|Make a payment|"
            r"Transactions Statements)",
            re.IGNORECASE,
        )

        for page in pages:
            for line in page.split("\n"):
                line = line.strip()
                if not line or skip_re.match(line):
                    continue

                m = tx_re.match(line)
                if not m:
                    continue

                month_str, day_str, year_str, desc, raw_amount = m.groups()
                date_str = self._normalize_date(f"{month_str} {day_str} {year_str}")
                if not date_str:
                    continue

                # Strip trailing city from description (", VANCOUVER" etc.)
                desc = re.sub(r",\s+[A-Z\s]+$", "", desc.strip())

                neg = raw_amount.startswith("-")
                amount = float(raw_amount.lstrip("-$").replace(",", ""))
                amount_cents = self.to_cents(-amount) if neg else self.to_cents(amount)

                transactions.append({
                    "date": date_str,
                    "description": desc.strip(),
                    "amount": amount_cents,
                    "account_hint": f"RBC Visa {acct_suffix}".strip(),
                    "account_type": "credit",
                    "source": "pdf",
                    "raw_text": line,
                })

        return transactions

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
            r"Here\s|Stay\s|Please\s|TM\s|®|https?://|From|Your\s|RBC\s*Private|"
            r"Royal\s*Bank|P\.O\.|Calgary|How\s*to|www\.|GST\s*Reg|Trademark|Registered|"
            r"Total\w*deposits|Total\w*withdrawals|account\s+statement|"
            r"\d+of\d+|\*[A-Z0-9]+\*)",
            re.IGNORECASE,
        )
        junk_re = re.compile(r"^[\d\-\*\s\(\)]+$|^[A-Z0-9_\-]{20,}$", re.IGNORECASE)

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

            # Strip date prefix if present — reset desc_parts on new date
            dm = date_re.match(line)
            if dm:
                month_num = self._month_num(dm.group(2))
                year = end_year if month_num < start_month else start_year
                current_date = self._normalize_date(f"{dm.group(1)} {dm.group(2)} {year}")
                desc_parts = []  # discard any accumulated header garbage on date change
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

                # Determine direction — keyword check overrides balance delta
                # to handle cases where prev_balance is stale (filtered transactions)
                is_withdrawal_keyword = bool(re.search(
                    r"e-transfer\s*sent|payment|withdrawal|atm|insurance|fees|dues|"
                    r"mortgage|loan|scheduled|transfer\s*to|misc\s*payment|auto\s*ins|"
                    r"online\s*banking\s*payment",
                    full_desc, re.IGNORECASE,
                ))
                is_deposit_keyword = bool(re.search(
                    r"payroll|deposit|e-transfer\s*rec|mobile.*deposit",
                    full_desc, re.IGNORECASE,
                ))
                if is_deposit_keyword:
                    is_deposit = True
                elif is_withdrawal_keyword:
                    is_deposit = False
                elif balance is not None and prev_balance is not None:
                    is_deposit = balance > prev_balance
                else:
                    is_deposit = False

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
        """
        RBC Visa format:
          DEC 23 DEC 24 SP PSYCHO BUNNY ST LAURENT QC $61.88
          74083425358100005845235
          JAN 13 JAN 13 PAYMENT - THANK YOU / PAIEMENT - MERCI -$6,364.53
          74510406013619985031409

        Two dates (transaction + posting), description, dollar amount with $ prefix.
        Reference number on next line (pure digits, 14+).
        Negative amounts (payments/credits) start with -$.
        """
        transactions = []
        year = self._extract_year(full_text)

        # Pattern: MMM DD MMM DD <desc> $amount  (or -$amount)
        tx_re = re.compile(
            r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+"
            r"(.+?)\s+(-?\$[\d,]+\.\d{2})\s*$",
            re.IGNORECASE,
        )
        ref_re = re.compile(r"^\d{10,}$")

        all_lines: list[str] = []
        for page in pages:
            all_lines.extend(page.split("\n"))

        # Detect year boundary: if statement crosses Dec→Jan, handle year rollover
        _, end_year, start_month = self._extract_period_years(full_text)

        for line in all_lines:
            line = line.strip()
            if not line or ref_re.match(line):
                continue

            m = tx_re.match(line)
            if not m:
                continue

            month_str, day_str, desc, raw_amount = m.groups()
            month_num = self._month_num(month_str)
            # Transactions in months after the start belong to end_year
            tx_year = end_year if month_num < start_month else (end_year - 1 if start_month > 1 else end_year)
            date_str = self._normalize_date(f"{month_str} {day_str} {tx_year}")
            if not date_str:
                continue

            desc = desc.strip()
            # Strip trailing junk appended from sidebar (e.g. "CONTACT US", "Customer Service...")
            desc = re.sub(r"\s+(CONTACT US|Customer Service.*|www\..*)$", "", desc, flags=re.IGNORECASE)

            # Parse amount: -$6,364.53 → payment (negative = credit to account = deposit)
            neg = raw_amount.startswith("-")
            amount = float(raw_amount.lstrip("-$").replace(",", ""))
            # Charges are positive amounts (money out), payments are negative (money in)
            amount_cents = self.to_cents(-amount) if neg else self.to_cents(amount)

            transactions.append({
                "date": date_str,
                "description": desc,
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
