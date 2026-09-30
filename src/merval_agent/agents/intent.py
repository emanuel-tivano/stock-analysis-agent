"""Conservatively classify explicitly requested analysis dimensions."""

import re
import unicodedata
from typing import Literal

from merval_agent.domain.models import RequestIntentAssessment

_TECHNICAL_DIMENSION = (
    r"\b(?:tecnic[oa]s?|tecnicamente|technical|tendencia|momentum|rsi|macd|"
    r"sobrecompra(?:d[oa])?|sobreventa|sobrevendid[oa])\b"
)
_TECHNICAL_SCOPE = r"\b(?:tecnic[oa]s?|tecnicamente|technical|tendencia|momentum)\b"
_FUNDAMENTAL_DIMENSION = r"\b(?:fundamental(?:es)?|fundamentos)\b"
_FULL_DIMENSION = r"\b(?:integral|completo|completa)\b"
_BASIS = (
    r"(?:usando|mediante|segun|a partir de|con base en|"
    r"bas(?:ad[oa]s?|and(?:ome|ote|ose))\s+en)"
)
_FUNDAMENTAL_EVIDENCE = (
    r"(?:balances?|estados?\s+(?:contables?|financieros?)|flujo\s+de\s+caja|"
    r"resultados?\s+contables?|patrimonio|deuda|roe|eps|fcf)"
)
_TECHNICAL_EVIDENCE = (
    r"(?:rsi|macd|medias?\s+moviles?|promedios?\s+moviles?|"
    r"bandas?\s+de\s+bollinger|ohlc|ohlcv)"
)


def _normalize(message: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", message.casefold()) if not unicodedata.combining(c)
    )


def _explicit_dimensions(text: str) -> tuple[bool, bool, bool]:
    technical = bool(re.search(_TECHNICAL_DIMENSION, text))
    technical_scope = bool(re.search(_TECHNICAL_SCOPE, text))
    fundamental = bool(re.search(_FUNDAMENTAL_DIMENSION, text))
    full = bool(re.search(_FULL_DIMENSION, text)) or (technical_scope and fundamental)
    return technical, fundamental, full


def _requires_evidence(text: str, evidence: str) -> bool:
    determiners = r"(?:(?:el|la|los|las|un|una|datos?|metricas?|indicadores?|del|de)\s+){0,4}"
    return bool(re.search(rf"\b{_BASIS}\s+{determiners}{evidence}\b", text))


def assess_request_intent(message: str) -> RequestIntentAssessment:
    """Classify only explicit, bounded domain contradictions in the original request."""
    text = _normalize(message)
    technical, fundamental, full = _explicit_dimensions(text)
    technical_scope = bool(re.search(_TECHNICAL_SCOPE, text))
    if full:
        return RequestIntentAssessment(status="MIXED", analysis_type="full")
    if technical_scope and _requires_evidence(text, _FUNDAMENTAL_EVIDENCE):
        return RequestIntentAssessment(
            status="CONTRADICTORY",
            analysis_type="technical",
            conflict_code="TECHNICAL_REQUIRES_FUNDAMENTAL_EVIDENCE",
        )
    if fundamental and _requires_evidence(text, _TECHNICAL_EVIDENCE):
        return RequestIntentAssessment(
            status="CONTRADICTORY",
            analysis_type="fundamental",
            conflict_code="FUNDAMENTAL_REQUIRES_TECHNICAL_EVIDENCE",
        )
    return RequestIntentAssessment(
        status="CLEAR",
        analysis_type=(
            "fundamental"
            if fundamental and not technical_scope
            else "technical"
            if technical and not fundamental
            else None
        ),
    )


def explicit_analysis_type(message: str) -> Literal["technical", "fundamental"] | None:
    text = _normalize(message)
    technical, fundamental, full = _explicit_dimensions(text)
    technical_scope = bool(re.search(_TECHNICAL_SCOPE, text))
    if full:
        return None
    if fundamental and not technical_scope:
        return "fundamental"
    return "technical" if technical and not fundamental else None


def explicit_full_request(message: str) -> bool:
    """Explicit unsupported scope; preserve legacy generic analysis requests."""
    _, _, full = _explicit_dimensions(_normalize(message))
    return full
