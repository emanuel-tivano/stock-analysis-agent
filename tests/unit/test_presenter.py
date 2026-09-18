from datetime import date

import pytest

from merval_agent.domain.models import (
    Dimension,
    ErrorInfo,
    Evidence,
    FinalAnalysis,
    IndicatorBasis,
    TechnicalAssessment,
    TechnicalMetrics,
    TechnicalSignal,
)
from merval_agent.presentation.presenter import present_analysis


def analysis(
    *,
    conclusion="BEARISH",
    confidence="MEDIUM",
    provisional=False,
    status="ANSWER",
    metrics=True,
    errors=None,
    assessment_status="PARTIAL",
):
    assessment = TechnicalAssessment(
        status=assessment_status,
        conclusion=conclusion,
        trend=conclusion,
        momentum="MIXED",
        momentum_state="IMPROVING_BUT_BEARISH",
        confirmation="UNCONFIRMED",
        confidence=confidence,
        as_of=date(2026, 9, 17),
        basis=IndicatorBasis(
            history_as_of=date(2026, 9, 16),
            quote_as_of=date(2026, 9, 17) if provisional else None,
            quote_provisional=provisional,
            quote_in_indicators=provisional,
            policy="INCLUDE_PROVISIONAL_OHLC" if provisional else "HISTORY_ONLY",
        ),
        signals={
            "rsi14": TechnicalSignal(
                signal="BEARISH", explanation="RSI14 44.50: zona neutral, sesgo bajista."
            ),
            "macd_zero": TechnicalSignal(
                signal="BEARISH", explanation="MACD / cero: -1.00 por debajo de 0.00."
            ),
            "macd_signal": TechnicalSignal(
                signal="BULLISH", explanation="MACD / señal: -1.00 por encima de -1.20."
            ),
            "macd_histogram": TechnicalSignal(
                signal="BULLISH",
                explanation="Histograma MACD / cero: 0.20 por encima de 0.00.",
            ),
        },
        warnings=["Advertencia calculada por el dominio."],
    )
    values = (
        TechnicalMetrics(
            current_price=100,
            sma20=105,
            sma50=110,
            ema12=103,
            ema26=106,
            rsi14=44.5,
            macd=-1,
            macd_signal=-1.2,
            macd_histogram=0.2,
            change_percent=-3.5,
            period_high=120,
            period_low=95,
            sample_size=60,
        )
        if metrics
        else None
    )
    evidence = [
        Evidence(
            source="https://market.test/history",
            chunk_id="trace:ohlcv",
            text="Datos",
            score=1,
            kind="DATA",
        )
    ]
    if provisional:
        evidence.append(
            Evidence(
                source="https://market.test/quote",
                chunk_id="trace:quote",
                text="Quote",
                score=1,
                kind="DATA",
                metadata={"provisional": True},
            )
        )
    return FinalAnalysis(
        status=status,
        ticker="GGAL",
        company_name="Grupo Financiero Galicia",
        analysis_type="technical",
        as_of=date(2026, 9, 17),
        executive_summary="Resumen determinístico.",
        technical=Dimension(
            status=assessment_status if conclusion == "UNAVAILABLE" else conclusion,
            metrics=values,
            assessment=assessment,
            evidence=evidence,
            limitations=["Limitación técnica."],
        ),
        trace_id="trace-1",
        session_id="session-1",
        errors=errors or [],
    )


@pytest.mark.parametrize(
    "signal,label",
    [("BEARISH", "Bajista"), ("BULLISH", "Alcista"), ("MIXED", "Mixto")],
)
def test_presenter_translates_conclusion(signal, label):
    presented = present_analysis(analysis(conclusion=signal))

    assert presented.conclusion.code == signal
    assert presented.conclusion.label == label
    assert presented.executive_summary == "Resumen determinístico."


def test_presenter_translates_confidence_momentum_and_provisional_data():
    presented = present_analysis(analysis(provisional=True))

    assert presented.confidence.label == "Media"
    assert "Mejora de corto plazo" in presented.momentum_state.label
    assert presented.momentum_state.short_label == "Mejorando, pero todavía bajista"
    assert presented.rsi.value == 44.5
    assert presented.rsi.summary == "44,50 — Neutral con sesgo bajista"
    assert presented.macd_summary == "Mejora de corto plazo, pero todavía bajo cero."
    assert presented.sources[-1].provisional is True
    assert presented.warnings == [
        "Datos provisionales: la última cotización corresponde a la rueda actual, "
        "por lo que los indicadores pueden cambiar hasta el cierre."
    ]
    assert presented.user_message is None


@pytest.mark.parametrize(
    ("zero_signal", "signal_signal", "expected"),
    [
        ("BULLISH", "NEUTRAL", "Permanece sobre cero y en línea con su señal."),
        ("BEARISH", "NEUTRAL", "Permanece bajo cero y en línea con su señal."),
        ("NEUTRAL", "BULLISH", "Está cerca de cero y por encima de su señal."),
        ("NEUTRAL", "BEARISH", "Está cerca de cero y por debajo de su señal."),
        ("NEUTRAL", "NEUTRAL", "Está cerca de cero y en línea con su señal."),
    ],
)
def test_presenter_summarizes_neutral_macd_combinations(zero_signal, signal_signal, expected):
    result = analysis()
    result.technical.assessment.signals["macd_zero"].signal = zero_signal
    result.technical.assessment.signals["macd_signal"].signal = signal_signal

    assert present_analysis(result).macd_summary == expected


def test_presenter_handles_unavailable_optional_and_partial_fields():
    result = analysis(
        conclusion="UNAVAILABLE",
        confidence="UNAVAILABLE",
        status="ABSTAIN",
        metrics=False,
        assessment_status="INSUFFICIENT_DATA",
    )
    result.technical.assessment.missing_indicators = {"sma50": "Requiere 50 observaciones."}
    presented = present_analysis(result)

    assert presented.conclusion.label == "No disponible para esta evaluación"
    assert presented.confidence.label == "No disponible"
    assert presented.rsi.display == "No disponible"
    assert presented.rsi.summary == "No disponible"
    assert presented.technical_details.sample_size is None
    assert presented.technical_details.missing_indicators["sma50"].startswith("Requiere")
    assert "información suficiente" in presented.user_message
    assert "Advertencia calculada" in presented.technical_details.warnings[0]


@pytest.mark.parametrize(
    "code,expected",
    [
        ("EXTERNAL_SERVICE", "datos de mercado"),
        ("LLM_FAILURE", "no respondió a tiempo"),
        ("INTERNAL_ERROR", "trace-1"),
    ],
)
def test_presenter_translates_failures_without_internal_details(code, expected):
    result = analysis(
        status="ERROR",
        errors=[ErrorInfo(code=code, message="private stack trace")],
        assessment_status="SOURCE_ERROR" if code == "EXTERNAL_SERVICE" else "PARTIAL",
    )

    presented = present_analysis(result)

    assert expected in presented.user_message
    assert "private stack trace" not in presented.user_message


def test_presenter_drops_unsafe_source_urls():
    result = analysis()
    result.technical.evidence.append(
        Evidence(
            source="javascript:alert(1)",
            chunk_id="unsafe",
            text="Unsafe",
            score=1,
            kind="DATA",
        )
    )

    assert [source.url for source in present_analysis(result).sources] == [
        "https://market.test/history"
    ]


def test_presenter_consolidates_equivalent_provisional_warnings_without_mutating_domain():
    result = analysis(provisional=True)
    result.technical.assessment.warnings.extend(
        [
            "Última barra provisional; sus indicadores pueden cambiar.",
            "Los datos de la rueda actual son provisionales y pueden cambiar.",
        ]
    )
    result.technical.limitations.append(
        "La última barra es provisional: los indicadores incluyen la quote y pueden cambiar."
    )
    original = result.model_dump(mode="json")

    presented = present_analysis(result)

    assert presented.warnings == [
        "Datos provisionales: la última cotización corresponde a la rueda actual, "
        "por lo que los indicadores pueden cambiar hasta el cierre."
    ]
    assert len(presented.technical_details.warnings) == 5
    assert result.model_dump(mode="json") == original


def test_presenter_consolidates_volume_warnings_and_keeps_audit_details():
    result = analysis()
    result.technical.assessment.warnings.append(
        "Volumen incompleto: promedio de toda la muestra no disponible."
    )
    result.technical.limitations.append(
        "Volumen desconocido en parte de la muestra; average_volume no se calcula."
    )

    presented = present_analysis(result)

    assert presented.warnings == ["Volumen: no hay información suficiente para confirmar la señal."]
    assert sum("Volumen" in warning for warning in presented.technical_details.warnings) == 2


def test_presenter_keeps_technical_warning_out_of_main_warnings():
    result = analysis()
    result.technical.assessment.warnings = [
        "Vigencia con tolerancia de días calendario; no certifica cierre."
    ]

    presented = present_analysis(result)

    assert presented.warnings == []
    assert presented.technical_details.warnings == [
        "Vigencia con tolerancia de días calendario; no certifica cierre.",
        "Limitación técnica.",
    ]


def test_presenter_formats_numbers_in_spanish_in_one_backend_layer():
    result = analysis()
    result.technical.metrics.current_price = 6955
    result.technical.metrics.period_high = 7134.5
    result.technical.metrics.change_percent = 13.92

    presented = present_analysis(result)
    indicators = {metric.key: metric for metric in presented.indicators}

    assert indicators["current_price"].display == "6.955,00"
    assert indicators["period_high"].display == "7.134,50"
    assert indicators["change_percent"].display == "13,92 %"
    assert indicators["current_price"].value == 6955


def test_presenter_keeps_full_signal_explanations_in_technical_details():
    explanations = present_analysis(analysis()).technical_details.signal_explanations

    assert [item.label for item in explanations] == [
        "RSI",
        "MACD respecto de cero",
        "MACD respecto de su señal",
        "Histograma MACD",
    ]
    assert explanations[1].text.startswith("MACD / cero")
