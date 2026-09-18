from collections.abc import Iterable
from urllib.parse import urlsplit

from merval_agent.domain.models import FinalAnalysis, TechnicalAssessment, TechnicalMetrics

from .models import (
    ChatResponse,
    PresentedExplanation,
    PresentedMetric,
    PresentedSource,
    PresentedValue,
    TechnicalDetails,
)

SIGNAL_LABELS = {
    "BULLISH": "Alcista",
    "BEARISH": "Bajista",
    "NEUTRAL": "Neutral",
    "MIXED": "Mixto",
    "UNAVAILABLE": "No disponible para esta evaluación",
}

CONFIDENCE_LABELS = {
    "HIGH": "Alta",
    "MEDIUM": "Media",
    "LOW": "Baja",
    "UNAVAILABLE": "No disponible",
}

MOMENTUM_STATE_LABELS = {
    **SIGNAL_LABELS,
    "IMPROVING_BUT_BEARISH": ("Mejora de corto plazo dentro de una estructura todavía bajista"),
    "WEAKENING_BUT_BULLISH": (
        "Pérdida de impulso de corto plazo dentro de una estructura todavía alcista"
    ),
    "RECOVERY_FADING_BUT_BEARISH": (
        "La mejora de corto plazo pierde fuerza dentro de una estructura bajista"
    ),
}

MOMENTUM_STATE_SHORT_LABELS = {
    "IMPROVING_BUT_BEARISH": "Mejorando, pero todavía bajista",
    "WEAKENING_BUT_BULLISH": "Perdiendo impulso, pero todavía alcista",
    "RECOVERY_FADING_BUT_BEARISH": "La mejora pierde fuerza; estructura bajista",
}

CONFIRMATION_LABELS = {
    "ALIGNED": "Indicadores alineados",
    "UNCONFIRMED": "Sin confirmación suficiente",
    "UNAVAILABLE": "Confirmación no disponible",
}

METRICS = (
    ("current_price", "Precio actual"),
    ("sma20", "SMA20"),
    ("sma50", "SMA50"),
    ("ema12", "EMA12"),
    ("ema26", "EMA26"),
    ("rsi14", "RSI14"),
    ("macd", "MACD"),
    ("macd_signal", "Señal MACD"),
    ("macd_histogram", "Histograma MACD"),
    ("change_percent", "Variación del período"),
    ("period_high", "Máximo del período"),
    ("period_low", "Mínimo del período"),
)

PROVISIONAL_WARNING = (
    "Datos provisionales: la última cotización corresponde a la rueda actual, "
    "por lo que los indicadores pueden cambiar hasta el cierre."
)
VOLUME_WARNING = "Volumen: no hay información suficiente para confirmar la señal."
STATUS_WARNINGS = {
    "INSUFFICIENT_DATA": "Datos insuficientes: no hay información suficiente para concluir.",
    "SOURCE_ERROR": "Fuente temporalmente no disponible: no se pudieron obtener datos de mercado.",
    "STALE": "Datos desactualizados: la lectura técnica puede no representar el estado actual.",
    "INVALID_DATA": "Datos inválidos: no fue posible validar una lectura técnica.",
    "UNVERIFIED": "Fuente sin verificar: la lectura no cuenta con evidencia de mercado validada.",
}

SIGNAL_DETAIL_LABELS = {
    "rsi14": "RSI",
    "macd_zero": "MACD respecto de cero",
    "macd_signal": "MACD respecto de su señal",
    "macd_histogram": "Histograma MACD",
}


def translated(
    code: str, labels: dict[str, str], short_labels: dict[str, str] | None = None
) -> PresentedValue:
    label = labels.get(code, code.replace("_", " ").title())
    return PresentedValue(
        code=code,
        label=label,
        short_label=(short_labels or {}).get(code, label),
    )


def _format_number(value: float | int) -> str:
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _metric(key: str, label: str, value: float | int | None) -> PresentedMetric:
    if value is None:
        display = "No disponible"
    elif key == "change_percent":
        display = f"{_format_number(value)} %"
    elif key == "sample_size":
        display = str(value)
    else:
        display = _format_number(value)
    return PresentedMetric(key=key, label=label, value=value, display=display)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _safe_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _human_message(result: FinalAnalysis) -> str | None:
    codes = {error.code for error in result.errors}
    assessment = result.technical.assessment
    if result.status == "ANSWER":
        return None
    if result.status == "CLARIFY":
        return result.executive_summary or "Indicá el ticker o el nombre de la empresa."
    if result.status == "ABSTAIN":
        if assessment and assessment.status == "INSUFFICIENT_DATA":
            return "No hay información suficiente para obtener una conclusión técnica."
        return result.executive_summary or "No hay información suficiente para responder."
    if assessment and assessment.status == "SOURCE_ERROR" or "EXTERNAL_SERVICE" in codes:
        return "No pude obtener los datos de mercado en este momento. Intentá nuevamente más tarde."
    if "LLM_FAILURE" in codes:
        return (
            "El servicio de análisis no respondió a tiempo o no está disponible en este momento. "
            "Intentá nuevamente más tarde."
        )
    return f"Ocurrió un error interno. Usá el identificador {result.trace_id} para reportarlo."


def _assessment(result: FinalAnalysis) -> TechnicalAssessment:
    return result.technical.assessment or TechnicalAssessment(status="INSUFFICIENT_DATA")


def _metrics(result: FinalAnalysis) -> TechnicalMetrics:
    return result.technical.metrics or TechnicalMetrics()


def _result_type(result: FinalAnalysis) -> str:
    statuses = {result.technical.status, result.fundamental.status}
    if "ASSET_NOT_FOUND" in statuses:
        return "asset_not_found"
    if "AMBIGUOUS_ASSET" in statuses:
        return "ambiguous_asset"
    if result.ticker and result.technical.status == "INSUFFICIENT_DATA":
        return "insufficient_market_data"
    if result.status == "ANSWER":
        return "successful_analysis"
    return "other"


def _presentation_warnings(
    result: FinalAnalysis, assessment: TechnicalAssessment, metrics: TechnicalMetrics
) -> list[str]:
    original = [*assessment.warnings, *result.technical.limitations]
    normalized = " ".join(original).casefold()
    warnings = []
    if assessment.basis.quote_provisional or "provisional" in normalized:
        warnings.append(PROVISIONAL_WARNING)
    volume_unavailable = metrics.average_volume is None and "volumen" in normalized
    if volume_unavailable or any(
        phrase in normalized
        for phrase in (
            "volumen incompleto",
            "volumen desconocido",
            "confirmación por volumen no evaluable",
        )
    ):
        warnings.append(VOLUME_WARNING)
    if assessment.status in STATUS_WARNINGS:
        warnings.append(STATUS_WARNINGS[assessment.status])
    return _unique(warnings)


def _rsi_summary(metric: PresentedMetric, assessment: TechnicalAssessment) -> str:
    if metric.value is None:
        return metric.display
    signal = assessment.signals.get("rsi14")
    if signal is None:
        return metric.display
    explanation = signal.explanation.casefold()
    if "sobrecompra" in explanation:
        interpretation = "Zona de sobrecompra"
    elif "sobreventa" in explanation:
        interpretation = "Zona de sobreventa"
    elif "zona neutral" in explanation and "sesgo bajista" in explanation:
        interpretation = "Neutral con sesgo bajista"
    elif "zona neutral" in explanation and "sesgo alcista" in explanation:
        interpretation = "Neutral con sesgo alcista"
    elif "zona neutral" in explanation:
        interpretation = "Zona neutral"
    else:
        interpretation = translated(signal.signal, SIGNAL_LABELS).label
    return f"{metric.display} — {interpretation}"


def _macd_summary(assessment: TechnicalAssessment) -> str:
    zero = assessment.signals.get("macd_zero")
    signal = assessment.signals.get("macd_signal")
    if zero is None or signal is None:
        return "No disponible para esta evaluación."
    summaries = {
        ("BEARISH", "BULLISH"): "Mejora de corto plazo, pero todavía bajo cero.",
        ("BULLISH", "BEARISH"): "Pierde impulso de corto plazo, pero todavía sobre cero.",
        ("BEARISH", "BEARISH"): "Continúa bajo cero y por debajo de su señal.",
        ("BULLISH", "BULLISH"): "Continúa sobre cero y por encima de su señal.",
        ("BULLISH", "NEUTRAL"): "Permanece sobre cero y en línea con su señal.",
        ("BEARISH", "NEUTRAL"): "Permanece bajo cero y en línea con su señal.",
        ("NEUTRAL", "BULLISH"): "Está cerca de cero y por encima de su señal.",
        ("NEUTRAL", "BEARISH"): "Está cerca de cero y por debajo de su señal.",
        ("NEUTRAL", "NEUTRAL"): "Está cerca de cero y en línea con su señal.",
    }
    return summaries.get(
        (zero.signal, signal.signal),
        "Las señales del MACD no permiten una lectura resumida.",
    )


def present_analysis(result: FinalAnalysis) -> ChatResponse:
    """Build a deterministic, user-facing projection without changing domain conclusions."""
    result_type = _result_type(result)
    if result_type in ("asset_not_found", "ambiguous_asset"):
        return ChatResponse(
            status=result.status,
            result_type=result_type,
            heading=(
                "Activo no identificado"
                if result_type == "asset_not_found"
                else "Necesito que aclares el activo"
            ),
            user_message=result.executive_summary,
            executive_summary=result.executive_summary,
            trace_id=result.trace_id,
            session_id=result.session_id,
        )
    assessment = _assessment(result)
    metrics = _metrics(result)
    conclusion = translated(assessment.conclusion, SIGNAL_LABELS)
    confidence = translated(assessment.confidence, CONFIDENCE_LABELS)
    trend = translated(assessment.trend, SIGNAL_LABELS)
    momentum = translated(assessment.momentum, SIGNAL_LABELS)
    momentum_state = translated(
        assessment.momentum_state,
        MOMENTUM_STATE_LABELS,
        MOMENTUM_STATE_SHORT_LABELS,
    )
    confirmation = translated(assessment.confirmation, CONFIRMATION_LABELS)

    indicators = [_metric(key, label, getattr(metrics, key)) for key, label in METRICS]
    rsi = next(item for item in indicators if item.key == "rsi14")
    rsi.summary = _rsi_summary(rsi, assessment)

    sources = []
    seen_urls = set()
    for evidence in result.technical.evidence:
        if evidence.source in seen_urls or not _safe_url(evidence.source):
            continue
        seen_urls.add(evidence.source)
        sources.append(
            PresentedSource(
                url=evidence.source,
                data_date=assessment.basis.quote_as_of
                if evidence.metadata.get("provisional")
                else assessment.basis.history_as_of or result.as_of,
                provisional=bool(evidence.metadata.get("provisional", False)),
            )
        )

    technical_details = TechnicalDetails(
        trend=trend,
        momentum=momentum,
        momentum_state=momentum_state,
        confirmation=confirmation,
        confidence=confidence,
        sample_size=metrics.sample_size or None,
        sample_size_display=(
            f"{metrics.sample_size:,}".replace(",", ".") if metrics.sample_size else "No disponible"
        ),
        missing_indicators=assessment.missing_indicators,
        warnings=_unique([*assessment.warnings, *result.technical.limitations]),
        signal_explanations=[
            PresentedExplanation(label=SIGNAL_DETAIL_LABELS[key], text=signal.explanation)
            for key, signal in assessment.signals.items()
            if key in SIGNAL_DETAIL_LABELS
        ],
        trace_id=result.trace_id,
    )
    heading = " · ".join(part for part in (result.ticker, result.company_name) if part)
    if not heading:
        heading = "Stock Analysis Agent"
    return ChatResponse(
        status=result.status,
        result_type=result_type,
        ticker=result.ticker,
        company_name=result.company_name,
        heading=heading,
        user_message=_human_message(result),
        executive_summary=result.executive_summary,
        conclusion=conclusion,
        confidence=confidence,
        trend=trend,
        momentum=momentum,
        momentum_state=momentum_state,
        rsi=rsi,
        macd_summary=_macd_summary(assessment),
        indicators=indicators,
        sources=sources,
        warnings=_presentation_warnings(result, assessment, metrics),
        technical_details=technical_details,
        trace_id=result.trace_id,
        session_id=result.session_id,
    )
