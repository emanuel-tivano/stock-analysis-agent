from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from merval_agent.agents.finalization import _pending_review
from merval_agent.domain.actions import (
    ApproveActionRequest,
    digest,
    requests_review,
    transition_action,
)
from merval_agent.domain.models import EditorialOptions


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Prepará un informe técnico de GGAL para revisión.", True),
        ("Publicar informe técnico de BMA", True),
        ("Finalizá el informe técnico de PAMP", True),
        ("Confirmá el informe técnico de GGAL", True),
        ("Analizá técnicamente GGAL", False),
        ("No publiques un informe técnico de GGAL", False),
        ("No preparar un informe técnico de GGAL", False),
        ("Prepará un informe fundamental de GGAL", False),
        ("¿Qué es un informe técnico?", False),
    ],
)
def test_explicit_review_gate(message, expected):
    assert requests_review(message) is expected


def test_normalized_hash_is_stable_and_sensitive_to_payload():
    assert digest({"b": 1, "a": "revisión"}) == digest({"a": "revisión", "b": 1})
    assert digest({"focus": "trend"}) != digest({"focus": "risk"})
    assert digest(EditorialOptions()) == digest(EditorialOptions().model_dump())


@pytest.mark.parametrize(
    "field",
    [
        "ticker",
        "currency",
        "metrics",
        "as_of",
        "snapshot_sha256",
        "confidence",
        "signals",
        "source",
    ],
)
def test_editorial_extras_are_rejected(field):
    with pytest.raises(ValidationError):
        EditorialOptions.model_validate({field: "change"})


def test_length_boundaries_and_comment_is_not_an_instruction():
    edit = EditorialOptions(review_note="Otro ticker requiere una ejecución nueva. " + "x" * 450)
    assert edit.focus == "overview"
    assert ApproveActionRequest(
        session_id="x" * 100, idempotency_key="x" * 100, expected_version=1, comment="x" * 500
    )


def test_unknown_domain_decision_cannot_approve(make_agent):
    agent, repository = make_agent()
    result = agent.run("Analizá técnicamente GGAL")
    state = repository.records[-1][0]
    action = _pending_review(state, result, "Prepará un informe técnico de GGAL")
    assert action is not None
    request = ApproveActionRequest(
        session_id=action.session_id,
        idempotency_key="invalid-decision",
        expected_version=action.version,
    )

    with pytest.raises(ValueError, match="Unsupported decision"):
        transition_action(action, "unknown", request, decided_at=datetime.now(UTC))
    assert action.status == "PENDING"
    assert action.human_decision is None
