from .base import BaseParser, detect_bank
from .rbc import RBCParser
from .scotiabank import ScotiabankParser
from .cibc import CIBCParser
from .bmo import BMOParser
from .amex import AmexParser

ALL_PARSERS = [RBCParser, ScotiabankParser, CIBCParser, BMOParser, AmexParser]

__all__ = ["BaseParser", "detect_bank", "ALL_PARSERS", "RBCParser", "ScotiabankParser", "CIBCParser", "BMOParser", "AmexParser"]
