"""Pure technical rules. Confidence describes evidence, never forecast probability."""

from datetime import date, datetime, timedelta
from math import isclose
from statistics import fmean

from .models import (
    IndicatorBasis,
    MarketHistory,
    Signal,
    TechnicalAssessment,
    TechnicalMetrics,
    TechnicalSignal,
)
from .policy import MARKET_TIMEZONE

WINDOWS = {
    "sma20": 20,
    "sma50": 50,
    "ema12": 12,
    "ema26": 26,
    "rsi14": 15,
    "macd": 26,
    "macd_signal": 34,
    "macd_histogram": 34,
}
MINIMUM_SAMPLE = 15
LABELS = {
    "BULLISH": "alcista",
    "BEARISH": "bajista",
    "NEUTRAL": "neutral",
    "MIXED": "mixta",
    "UNAVAILABLE": "no disponible",
}


def is_answerable(assessment: TechnicalAssessment | None) -> bool:
    """Whether Python has enough verified evidence to publish technical signals."""
    return assessment is not None and assessment.status in ("COMPLETE", "PARTIAL")


def stale_date(
    last: date, today: date, grace_days: int, holidays: frozenset[date] = frozenset()
) -> bool:
    """Calendar grace plus last possible session; no invented exchange calendar.

    The current session is not assumed closed. Callers may supply verified closures.
    Default seven-day grace tolerates normal weekends and holiday breaks.
    """
    previous = today - timedelta(days=1)
    while previous.weekday() >= 5 or previous in holidays:
        previous -= timedelta(days=1)
    return last < previous and (today - last).days > grace_days


def combine(signals: list[Signal]) -> Signal:
    available = set(signals) - {"UNAVAILABLE", "NEUTRAL"}
    if "MIXED" in available or {"BULLISH", "BEARISH"} <= available:
        return "MIXED"
    if available:
        return next(iter(available))
    return "NEUTRAL" if any(s != "UNAVAILABLE" for s in signals) else "UNAVAILABLE"


def assess(
    history: MarketHistory | None,
    metrics: TechnicalMetrics | None,
    at: datetime,
    stale_after_days: int = 7,
    holidays: frozenset[date] = frozenset(),
) -> TechnicalAssessment:
    result = TechnicalAssessment(status="INSUFFICIENT_DATA")
    if not history or not history.bars:
        result.warnings.append("No hay observaciones de mercado utilizables.")
        return result
    # Revalidate even model_copy/model_construct inputs, which bypass Pydantic validation.
    try:
        history = MarketHistory.model_validate(history.model_dump())
        if metrics:
            metrics = TechnicalMetrics.model_validate(metrics.model_dump())
    except ValueError:
        result.status, result.freshness = "INVALID_DATA", "INVALID"
        result.warnings.append(
            "Serie o indicadores inválidos: revisar valores, orden y duplicados."
        )
        return result
    today = at.astimezone(MARKET_TIMEZONE).date()
    result.as_of = history.bars[-1].date
    result.fetched_at = history.fetched_at
    included = history.enrichment_status == "appended"
    base_date = history.bars[-2].date if included else result.as_of
    quote = history.quote
    result.basis = IndicatorBasis(
        history_as_of=base_date,
        resolved_variant=history.resolved_variant,
        range=history.range,
        indicators_as_of=result.as_of,
        history_fetched_at=history.fetched_at,
        quote_as_of=quote.bar.date if quote else None,
        quote_observed_at=quote.observed_at if quote else None,
        quote_fetched_at=quote.fetched_at if quote else None,
        quote_price=quote.bar.close if quote else None,
        quote_provisional=quote is not None,
        quote_in_indicators=included,
        policy="INCLUDE_PROVISIONAL_OHLC" if included else "HISTORY_ONLY",
    )
    fetched_date = history.fetched_at.astimezone(MARKET_TIMEZONE).date()
    if (
        result.as_of > today
        or history.fetched_at > at
        or base_date > fetched_date
        or (quote and (quote.observed_at > quote.fetched_at or quote.fetched_at > at))
    ):
        result.status, result.freshness = "INVALID_DATA", "INVALID"
        result.warnings.append("Fechas futuras o histórico posterior a su recepción.")
        return result
    stale = history.stale or stale_date(base_date, today, stale_after_days, holidays)
    result.freshness = "STALE" if stale else "RECENT"
    result.warnings.append(
        "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre."
    )
    if stale:
        result.status = "STALE"
        result.warnings.append(
            "El histórico está desactualizado; una quote no renueva su vigencia."
        )
        return result
    if history.mode != "live":
        result.status = "UNVERIFIED"
        result.warnings.append("Origen demo o desconocido: no es evidencia de mercado verificada.")
        return result
    if not metrics:
        result.warnings.append("Indicadores aún no calculados por Python.")
        return result
    if metrics.sample_size != len(history.bars):
        result.status = "INVALID_DATA"
        result.warnings.append("La muestra de indicadores no coincide con el histórico.")
        return result
    for name, window in WINDOWS.items():
        if getattr(metrics, name) is None or len(history.bars) < window:
            result.missing_indicators[name] = (
                f"Requiere {window} observaciones; disponibles {len(history.bars)}."
                if len(history.bars) < window
                else "No disponible pese a contar con ventana suficiente."
            )
    if metrics.current_price is None or len(history.bars) < MINIMUM_SAMPLE:
        result.warnings.append(
            f"Se requiere precio actual y al menos {MINIMUM_SAMPLE} observaciones."
        )
        return result
    if metrics.current_price != history.bars[-1].close:
        result.status = "INVALID_DATA"
        result.warnings.append("El precio actual no coincide con la última observación.")
        return result
    result.status = "PARTIAL" if result.missing_indicators or history.discarded_rows else "COMPLETE"
    result.completion_reasons = [
        f"{name}: {reason}" for name, reason in result.missing_indicators.items()
    ]
    if history.discarded_rows:
        result.completion_reasons.append(
            f"Integridad parcial: {history.discarded_rows} filas descartadas."
        )
    if result.status == "COMPLETE":
        result.completion_reasons.append(
            "Todos los indicadores de precios requeridos disponibles; sin filas descartadas."
        )
    result.confidence = "HIGH" if result.status == "COMPLETE" else "MEDIUM"
    if history.quote or history.discarded_rows:
        result.confidence = "MEDIUM"
    if history.discarded_rows:
        result.warnings.append(f"Se descartaron {history.discarded_rows} filas inválidas.")
    if metrics.average_volume is None:
        result.confidence = "MEDIUM"
        result.warnings.append(
            "Volumen incompleto: promedio de toda la muestra no disponible; la confirmación local requiere 21 barras con volumen conocido."
        )
    if included:
        result.warnings.append("Última barra provisional; sus indicadores pueden cambiar.")

    def value(name):
        return None if name in result.missing_indicators else getattr(metrics, name)

    def comparison(key, left, right, title):
        if left is None or right is None:
            signal, text = "UNAVAILABLE", f"{title}: falta un indicador requerido."
        else:
            signal = (
                "NEUTRAL"
                if isclose(left, right, rel_tol=1e-9, abs_tol=1e-10)
                else ("BULLISH" if left > right else "BEARISH")
            )
            relation = {"NEUTRAL": "igual", "BULLISH": "por encima", "BEARISH": "por debajo"}[
                signal
            ]
            text = f"{title}: {left:.2f} {relation} de {right:.2f}."
        result.signals[key] = TechnicalSignal(signal=signal, explanation=text)

    comparison("price_sma20", metrics.current_price, value("sma20"), "Precio / SMA20")
    comparison("price_sma50", metrics.current_price, value("sma50"), "Precio / SMA50")
    comparison("sma20_sma50", value("sma20"), value("sma50"), "SMA20 / SMA50")
    comparison("ema12_ema26", value("ema12"), value("ema26"), "EMA12 / EMA26")
    rsi = value("rsi14")
    if rsi is None:
        result.signals["rsi14"] = TechnicalSignal(
            signal="UNAVAILABLE", explanation="RSI14 no disponible."
        )
    else:
        signal = "BULLISH" if rsi > 50 else "BEARISH" if rsi < 50 else "NEUTRAL"
        zone = "sobrecompra" if rsi >= 70 else "sobreventa" if rsi <= 30 else "zona neutral"
        result.signals["rsi14"] = TechnicalSignal(
            signal=signal,
            explanation=f"RSI14 {rsi:.2f}: {zone}, sesgo {LABELS[signal]}. No implica reversión automática.",
        )
    comparison("macd_signal", value("macd"), value("macd_signal"), "MACD / señal")
    comparison("macd_zero", value("macd"), 0, "MACD / cero")
    histogram = value("macd_histogram")
    previous_histogram = value("previous_macd_histogram")
    comparison("macd_histogram", histogram, 0, "Histograma MACD / cero")
    if histogram is not None:
        result.signals["macd_histogram"].explanation += (
            f" Magnitud absoluta {abs(histogram):.2f}; {histogram / metrics.current_price * 100:.4f}% del precio."
            " Una sola lectura no demuestra expansión ni un cruce reciente."
        )
    result.trend = combine(
        [
            result.signals[k].signal
            for k in ("price_sma20", "price_sma50", "sma20_sma50", "ema12_ema26")
        ]
    )
    result.momentum = combine(
        [result.signals[k].signal for k in ("rsi14", "macd_signal", "macd_zero")]
    )
    # Trend has precedence. MACD/signal is relative momentum, not a reversal vote.
    baseline = combine([result.signals[k].signal for k in ("rsi14", "macd_zero")])
    relative = result.signals["macd_signal"].signal
    territory = result.signals["macd_zero"].signal
    result.momentum_state = result.momentum
    if territory == "BEARISH" and relative == "BULLISH":
        if (
            histogram is not None
            and previous_histogram is not None
            and histogram < previous_histogram
        ):
            result.momentum_state = "RECOVERY_FADING_BUT_BEARISH"
        else:
            result.momentum_state = "IMPROVING_BUT_BEARISH"
    elif territory == "BULLISH" and relative == "BEARISH":
        result.momentum_state = "WEAKENING_BUT_BULLISH"
    result.conclusion = result.trend
    if result.trend == "UNAVAILABLE":
        result.conclusion = baseline
    elif baseline == "MIXED":
        result.conclusion = "MIXED"
    elif (
        baseline in ("BULLISH", "BEARISH")
        and result.trend in ("BULLISH", "BEARISH")
        and baseline != result.trend
    ):
        result.conclusion = "MIXED"
    elif result.trend == "NEUTRAL" and result.momentum == "MIXED":
        result.conclusion = "MIXED"
    result.confirmation = (
        "ALIGNED"
        if (
            result.trend in ("BULLISH", "BEARISH", "NEUTRAL")
            and baseline == result.trend
            and relative in (result.trend, "NEUTRAL")
            and result.status == "COMPLETE"
            and not included
        )
        else "UNCONFIRMED"
    )
    for direction in ("BULLISH", "BEARISH", "NEUTRAL"):
        keys = [k for k, s in result.signals.items() if s.signal == direction]
        if len(keys) > 1:
            result.agreements.append(f"Lectura {LABELS[direction]}: " + ", ".join(keys))
    bullish = [k for k, s in result.signals.items() if s.signal == "BULLISH"]
    bearish = [k for k, s in result.signals.items() if s.signal == "BEARISH"]
    if bullish and bearish:
        result.conflicts.append(
            "Señales alcistas ("
            + ", ".join(bullish)
            + ") coexisten con bajistas ("
            + ", ".join(bearish)
            + ")."
        )
    comparison("period_change", metrics.change_percent, 0, "Variación del período / cero")
    result.signals[
        "period_change"
    ].explanation += " Contexto de la muestra; no confirma la dirección actual."
    result.signals["volume"] = TechnicalSignal(
        signal="UNAVAILABLE" if metrics.average_volume is None else "NEUTRAL",
        explanation="Volumen no disponible: confirmación por volumen no evaluable."
        if metrics.average_volume is None
        else f"Volumen promedio {metrics.average_volume:.2f}; un promedio aislado no confirma dirección.",
    )
    # A local comparison, not a forecast. Never compare intraday volume to full bars.
    historical_bars = history.bars[:-1] if included else history.bars
    window = historical_bars[-21:]
    if len(window) == 21 and all(b.volume is not None for b in window):
        result.volume_as_of = window[-1].date
        result.volume_confirmation = "NOT_CONFIRMED"
        baseline_volume = fmean(b.volume for b in window[:-1])
        latest_volume = window[-1].volume
        direction = "NEUTRAL"
        if latest_volume > baseline_volume > 0:
            direction = (
                "BULLISH"
                if window[-1].close > window[-2].close
                else "BEARISH"
                if window[-1].close < window[-2].close
                else "NEUTRAL"
            )
        if direction != "NEUTRAL":
            result.volume_confirmation = "CONFIRMED"
        result.signals["volume"] = TechnicalSignal(
            signal=direction,
            explanation=(
                f"Volumen último {latest_volume:.2f} frente al promedio de las 20 barras previas "
                f"{baseline_volume:.2f}: "
                + (
                    f"acompaña el movimiento {LABELS[direction]} del último precio. "
                    if direction != "NEUTRAL"
                    else "sin confirmación direccional. "
                )
                + f" Evaluación sobre histórico al {window[-1].date}; excluye la quote provisional. "
                + "No certifica cierre de rueda ni anticipa precios."
            ),
        )
    else:
        result.signals["volume"] = TechnicalSignal(
            signal="UNAVAILABLE",
            explanation="Confirmación por volumen no evaluable: se requieren 21 barras históricas con volumen conocido.",
        )
    if result.conclusion == "UNAVAILABLE":
        result.status, result.confidence = "INSUFFICIENT_DATA", "UNAVAILABLE"
    return result


def narrative(assessment: TechnicalAssessment, sample_size: int) -> tuple[str, str]:
    available_momentum = "; ".join(
        assessment.signals[k].explanation
        for k in ("rsi14", "macd_zero", "macd_signal")
        if k in assessment.signals and assessment.signals[k].signal != "UNAVAILABLE"
    )
    momentum_text = {
        "IMPROVING_BUT_BEARISH": "El MACD continúa bajo cero, aunque está por encima de su señal: mejora relativa de corto plazo todavía en terreno bajista, sin confirmar reversión",
        "RECOVERY_FADING_BUT_BEARISH": (
            "El MACD continúa bajo cero y por encima de su señal, "
            "pero el histograma se contrae: la recuperación relativa "
            "pierde fuerza, sin confirmar todavía un cruce bajista"
        ),
        "WEAKENING_BUT_BULLISH": "El MACD continúa sobre cero, aunque está por debajo de su señal: pérdida de impulso de corto plazo todavía en terreno alcista, sin confirmar reversión",
        "BEARISH": "Momentum bajista sustentado por: " + available_momentum,
        "BULLISH": "Momentum alcista sustentado por: " + available_momentum,
        "NEUTRAL": "Los indicadores de momentum disponibles son neutrales",
        "MIXED": "Los componentes del momentum discrepan: "
        + "; ".join(
            assessment.signals[k].explanation
            for k in ("rsi14", "macd_zero", "macd_signal")
            if k in assessment.signals
        ),
        "UNAVAILABLE": "No hay indicadores suficientes para determinar momentum",
    }[assessment.momentum_state]
    summary = (
        f"Señal técnica {LABELS[assessment.conclusion]}; tendencia {LABELS[assessment.trend]} "
        f"según las medias y el precio. {momentum_text}. Muestra: {sample_size} observaciones "
        f"al {assessment.as_of}."
    )
    details = momentum_text + ". " + " ".join(s.explanation for s in assessment.signals.values())
    details += " Confirmación: " + (
        "indicadores alineados; no es certeza predictiva."
        if assessment.confirmation == "ALIGNED"
        else "sin confirmación conjunta de los indicadores."
    )
    details += " " + " ".join(assessment.conflicts)
    details += " Describe señales observadas, no un pronóstico ni una recomendación financiera personalizada."
    return summary, details.strip()
