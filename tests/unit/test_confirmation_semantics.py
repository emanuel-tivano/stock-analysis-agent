from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.models import Bar, MarketHistory, QuoteSnapshot
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess
from merval_agent.presentation.presenter import present_analysis

AT = datetime(2026, 9, 25, 12, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures" / "technical_v1"


def directional_history(
    direction: str,
    *,
    provisional: bool,
    volume_confirmation: str = "NOT_CONFIRMED",
    sample_size: int = 60,
) -> MarketHistory:
    start = date(2026, 9, 24) - timedelta(days=sample_size - 1)
    closes = [100 + i if direction == "BULLISH" else 200 - i for i in range(sample_size)]
    volumes: list[float | None] = [100] * sample_size
    evaluated_index = -2 if provisional else -1
    if volume_confirmation == "CONFIRMED":
        volumes[evaluated_index] = 200
    elif volume_confirmation == "UNAVAILABLE":
        volumes[evaluated_index] = None
    bars = [
        Bar(
            date=start + timedelta(days=i),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=volumes[i],
        )
        for i, close in enumerate(closes)
    ]
    quote = (
        QuoteSnapshot(
            bar=bars[-1],
            source="https://market.test/quote",
            observed_at=datetime(2026, 9, 24, 20, tzinfo=UTC),
            received_at=AT,
            currency="ARS",
        )
        if provisional
        else None
    )
    return MarketHistory(
        ticker="GGAL",
        range="6M",
        bars=bars,
        source="https://market.test/history",
        provider_fetched_at=AT,
        received_at=AT,
        mode="live",
        currency="ARS",
        quote=quote,
        enrichment_status="appended" if provisional else "not_requested",
    )


def frozen_history(name: str) -> MarketHistory:
    return MarketHistory.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))


def with_provisional_last_bar(history: MarketHistory) -> MarketHistory:
    quote = QuoteSnapshot(
        bar=history.bars[-1],
        source="https://market.test/quote",
        observed_at=datetime(2026, 9, 24, 20, tzinfo=UTC),
        received_at=history.received_at,
        currency=history.currency,
    )
    return history.model_copy(update={"quote": quote, "enrichment_status": "appended"})


@pytest.mark.parametrize("direction", ["BULLISH", "BEARISH"])
def test_alignment_is_independent_of_provisionality(direction):
    closed = directional_history(direction, provisional=False)
    provisional = directional_history(direction, provisional=True)
    closed_metrics = calculate(closed.bars)
    provisional_metrics = calculate(provisional.bars)

    closed_assessment = assess(closed, closed_metrics, AT)
    provisional_assessment = assess(provisional, provisional_metrics, AT)

    assert closed_metrics == provisional_metrics
    assert closed_assessment.status == provisional_assessment.status == "COMPLETE"
    assert closed_assessment.trend == provisional_assessment.trend == direction
    assert closed_assessment.momentum == provisional_assessment.momentum == direction
    assert closed_assessment.momentum_state == provisional_assessment.momentum_state == direction
    assert closed_assessment.conclusion == provisional_assessment.conclusion == direction
    assert closed_assessment.confirmation == provisional_assessment.confirmation == "ALIGNED"
    assert closed_assessment.confidence == "HIGH"
    assert provisional_assessment.confidence == "MEDIUM"
    assert not closed_assessment.basis.quote_provisional
    assert provisional_assessment.basis.quote_provisional
    assert provisional_assessment.basis.quote_in_indicators
    assert any("provisional" in warning.casefold() for warning in provisional_assessment.warnings)


def test_real_conflict_remains_unconfirmed_with_or_without_provisionality():
    closed = frozen_history("pamp_6m_20260924.json")
    provisional = with_provisional_last_bar(closed)
    metrics = calculate(closed.bars)

    closed_assessment = assess(closed, metrics, AT)
    provisional_assessment = assess(provisional, metrics, AT)

    assert closed_assessment.trend == provisional_assessment.trend == "MIXED"
    assert closed_assessment.conclusion == provisional_assessment.conclusion == "MIXED"
    assert closed_assessment.conflicts == provisional_assessment.conflicts
    assert closed_assessment.conflicts
    assert closed_assessment.confirmation == provisional_assessment.confirmation == "UNCONFIRMED"
    presented = present_analysis_from(provisional, provisional_assessment, metrics)
    assert (
        presented.technical_details.confirmation.label
        == "Sin alineación conjunta de los indicadores"
    )
    assert any("Datos provisionales" in warning for warning in presented.warnings)


@pytest.mark.parametrize("provisional", [False, True])
@pytest.mark.parametrize(
    "volume_confirmation",
    ["CONFIRMED", "NOT_CONFIRMED", "UNAVAILABLE"],
)
def test_volume_confirmation_is_orthogonal_to_alignment(provisional, volume_confirmation):
    history = directional_history(
        "BULLISH",
        provisional=provisional,
        volume_confirmation=volume_confirmation,
    )
    assessment = assess(history, calculate(history.bars), AT)

    assert assessment.confirmation == "ALIGNED"
    assert assessment.volume_confirmation == volume_confirmation
    assert assessment.volume_as_of == (
        None
        if volume_confirmation == "UNAVAILABLE"
        else history.bars[-2 if provisional else -1].date
    )


@pytest.mark.parametrize("volume_confirmation", ["CONFIRMED", "NOT_CONFIRMED"])
def test_conflict_and_volume_confirmation_are_independent(volume_confirmation):
    history = frozen_history("pamp_6m_20260924.json")
    if volume_confirmation == "CONFIRMED":
        bars = list(history.bars)
        bars[-1] = bars[-1].model_copy(update={"volume": 1_000_000_000})
        history = history.model_copy(update={"bars": bars})
    assessment = assess(history, calculate(history.bars), AT)

    assert assessment.conflicts
    assert assessment.confirmation == "UNCONFIRMED"
    assert assessment.volume_confirmation == volume_confirmation


def test_partial_provisional_assessment_does_not_claim_full_alignment():
    history = directional_history("BULLISH", provisional=True, sample_size=34)
    assessment = assess(history, calculate(history.bars), AT)

    assert assessment.status == "PARTIAL"
    assert assessment.confirmation == "UNCONFIRMED"
    assert assessment.basis.quote_in_indicators


def test_ggal_equivalent_preserves_every_technical_result_except_temporal_metadata():
    provisional = frozen_history("ggal_6m_20260924.json")
    closed = provisional.model_copy(update={"quote": None, "enrichment_status": "not_requested"})
    metrics = calculate(provisional.bars)
    provisional_assessment = assess(provisional, metrics, AT)
    closed_assessment = assess(closed, metrics, AT)

    assert calculate(closed.bars) == metrics
    for field in ("status", "trend", "momentum", "momentum_state", "conclusion", "conflicts"):
        assert getattr(provisional_assessment, field) == getattr(closed_assessment, field)
    assert provisional_assessment.confirmation == closed_assessment.confirmation == "ALIGNED"
    assert provisional_assessment.volume_confirmation == closed_assessment.volume_confirmation
    assert provisional_assessment.confidence == "MEDIUM"
    assert closed_assessment.confidence == "HIGH"


def test_agent_run_and_presenter_keep_alignment_and_provisional_warning(make_agent):
    history = directional_history("BEARISH", provisional=True, volume_confirmation="CONFIRMED")
    agent, _ = make_agent(clock=lambda: AT)
    agent.tools.tools["get_market_history"].handler = lambda args, state: history.model_dump(
        mode="json"
    )

    with TestClient(create_app(agent=agent, settings=Settings(_env_file=None))) as client:
        raw = client.post("/agent/run", json={"message": "Analizá técnicamente GGAL"})
        chat = client.post("/chat", json={"message": "Analizá técnicamente GGAL"})

    assert raw.status_code == chat.status_code == 200
    assert raw.json()["status"] == "ANSWER"
    assessment = raw.json()["technical"]["assessment"]
    assert assessment["confirmation"] == "ALIGNED"
    assert assessment["volume_confirmation"] == "CONFIRMED"
    assert assessment["basis"]["quote_provisional"] is True
    details = chat.json()["technical_details"]
    assert details["confirmation"]["label"] == "Indicadores alineados"
    assert details["volume_confirmation"]["code"] == "CONFIRMED"
    assert any("Datos provisionales" in warning for warning in chat.json()["warnings"])


def present_analysis_from(history, assessment, metrics):
    from merval_agent.agents.report import build_report
    from merval_agent.domain.models import AgentState, AssetResolution, UserIntent

    state = AgentState(
        user_request=f"Técnico {history.ticker}",
        status="ANSWER",
        intent=UserIntent(analysis_type="technical"),
        resolved_asset=AssetResolution(ticker=history.ticker, confidence=1),
        technical_data=history,
        technical_metrics=metrics,
        technical_assessment=assessment,
        technical_evaluated_at=AT,
    )
    return present_analysis(build_report(state, "", "", 7, reference_time=AT))
