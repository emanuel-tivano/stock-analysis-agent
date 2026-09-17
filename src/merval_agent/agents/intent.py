"""Normalize only an explicitly named analysis dimension, without choosing tools."""

import re
import unicodedata
from typing import Literal


def explicit_analysis_type(message: str) -> Literal["technical", "fundamental"] | None:
    text = "".join(
        c for c in unicodedata.normalize("NFKD", message.casefold()) if not unicodedata.combining(c)
    )
    technical = bool(
        re.search(
            r"\b(?:tecnic[oa]s?|tecnicamente|technical|tendencia|momentum|rsi|macd|"
            r"sobrecompra(?:d[oa])?|sobreventa|sobrevendid[oa])\b",
            text,
        )
    )
    fundamental = bool(re.search(r"\b(?:fundamental(?:es)?|fundamentos)\b", text))
    if technical == fundamental:
        return None
    return "technical" if technical else "fundamental"


def explicit_full_request(message: str) -> bool:
    """Explicit unsupported scope; preserve legacy generic analysis requests."""
    text = "".join(
        c for c in unicodedata.normalize("NFKD", message.casefold()) if not unicodedata.combining(c)
    )
    return bool(re.search(r"\b(?:integral|completo|completa)\b", text)) or (
        bool(re.search(r"\b(?:tecnic[oa]s?|tecnicamente|technical)\b", text))
        and bool(re.search(r"\b(?:fundamental(?:es)?|fundamentos)\b", text))
    )
