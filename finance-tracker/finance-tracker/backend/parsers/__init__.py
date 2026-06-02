from .base import BaseParser, detect_bank
from .rbc import RBCParser
from .scotiabank import ScotiabankParser
from .cibc import CIBCParser
from .bmo import BMOParser
from .amex import AmexParser
from .vancity import VancityParser

ALL_PARSERS = [RBCParser, ScotiabankParser, CIBCParser, BMOParser, AmexParser, VancityParser]

__all__ = ["BaseParser", "detect_bank", "ALL_PARSERS", "RBCParser", "ScotiabankParser", "CIBCParser", "BMOParser", "AmexParser", "VancityParser"]
