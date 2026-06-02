from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


class BaseParser(ABC):
    """Abstract base class for bank statement parsers."""

    bank_name: str = "Unknown"

    @classmethod
    @abstractmethod
    def detect(cls, text: str) -> bool:
        """Return True if this parser can handle the given PDF text."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, pdf_path: Path) -> list[dict]:
        """Parse a PDF and return list of transaction dicts."""
        raise NotImplementedError

    @staticmethod
    def clean_amount(raw: str) -> float:
        """
        Convert a string amount to a float.
        - Strips $, commas, spaces
        - Parentheses (123.45) → negative -123.45
        - Returns positive float; caller decides sign convention
        """
        raw = raw.strip()
        negative = raw.startswith("(") and raw.endswith(")")
        raw = raw.strip("()")
        raw = raw.replace("$", "").replace(",", "").replace(" ", "")
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        return -value if negative else value

    @staticmethod
    def to_cents(amount: float) -> int:
        return round(amount * 100)

    @staticmethod
    def parse_date(raw: str) -> Optional[str]:
        """
        Parse various date formats to ISO YYYY-MM-DD.
        Handles: Jan 01, Jan 01 2024, 01/01/2024, 2024-01-01, Jan. 1, 2024
        """
        import re
        from dateutil import parser as dateparser

        raw = raw.strip()
        if not raw:
            return None
        try:
            dt = dateparser.parse(raw, dayfirst=False)
            return dt.strftime("%Y-%m-%d") if dt else None
        except Exception:
            return None

    @staticmethod
    def get_text(pdf_path: Path) -> str:
        """Extract all text from a PDF."""
        if pdfplumber is None:
            raise ImportError("pdfplumber is not installed")
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n".join(pages)

    @staticmethod
    def get_pages(pdf_path: Path) -> list[str]:
        """Return list of text per page."""
        if pdfplumber is None:
            raise ImportError("pdfplumber is not installed")
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
            return pages


def detect_bank(pdf_path: Path) -> Optional[str]:
    """Auto-detect which bank a PDF belongs to."""
    from . import ALL_PARSERS

    try:
        pages = BaseParser.get_pages(pdf_path)
        first_pages = "\n".join(pages[:3])
    except Exception:
        return None

    for parser_cls in ALL_PARSERS:
        if parser_cls.detect(first_pages):
            return parser_cls.bank_name
    return None


def get_parser(pdf_path: Path) -> Optional[BaseParser]:
    """Return the appropriate parser instance for a PDF."""
    from . import ALL_PARSERS

    try:
        pages = BaseParser.get_pages(pdf_path)
        first_pages = "\n".join(pages[:3])
    except Exception:
        return None

    for parser_cls in ALL_PARSERS:
        if parser_cls.detect(first_pages):
            return parser_cls()
    return None
