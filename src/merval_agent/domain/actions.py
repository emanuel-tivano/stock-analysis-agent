"""Typed, immutable financial snapshots and editorial-only report finalization."""

import hashlib
import json
import re
import unicodedata
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from .models import (
    EditorialOptions,
    FinalAnalysis,
    MarketHistory,
    Model,
    PendingActionResponse,
    ReportPublication,
    now,
)
from .technical_assessment import is_answerable

OpaqueKey = Annotated[
    str, StringConstraints(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
]
SessionKey = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
]


def canonical(value: Model | dict) -> str:
    if isinstance(value, Model):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Model | dict) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def requests_review(message: str) -> bool:
    text = "".join(
        c for c in unicodedata.normalize("NFKD", message.lower()) if not unicodedata.combining(c)
    )
    # Authorization is derived from the user's request, never from the LLM's intent.
    return (
        bool(re.search(r"\binforme\s+tecnico\b", text))
        and bool(
            re.search(
                r"\b(?:prepara|preparar|finaliza|finalizar|publica|publicar|confirma|confirmar)\b",
                text,
            )
        )
        and not bool(
            re.search(r"\bno\s+(?:lo\s+)?(?:prepar\w*|finaliz\w*|public\w*|confirm\w*)", text)
        )
    )


class ApproveActionRequest(Model):
    idempotency_key: OpaqueKey
    expected_version: int = Field(ge=1, strict=True)
    session_id: SessionKey
    comment: str = Field(default="", max_length=500, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$")


class ModifyActionRequest(ApproveActionRequest):
    changes: EditorialOptions


class RejectActionRequest(ApproveActionRequest):
    pass


class EvidenceSnapshot(Model):
    report: FinalAnalysis
    history: MarketHistory
    evaluated_at: AwareDatetime

    @model_validator(mode="after")
    def consistent(self):
        r = self.report
        if (
            r.status != "ANSWER"
            or r.analysis_type != "technical"
            or r.pending_action is not None
            or r.publication is not None
            or not is_answerable(r.technical.assessment)
            or not r.technical.metrics
            or r.ticker != self.history.ticker
            or r.as_of != self.history.bars[-1].date
            or r.technical.metrics.sample_size != len(self.history.bars)
        ):
            raise ValueError("Snapshot is not a reviewable technical analysis")
        return self


class PendingAction(Model):
    action_id: UUID = Field(default_factory=uuid4)
    trace_id: str
    session_id: SessionKey
    action_type: Literal["FINALIZE_TECHNICAL_REPORT"] = "FINALIZE_TECHNICAL_REPORT"
    status: Literal["PENDING", "MODIFIED", "APPROVED", "REJECTED", "EXECUTED"] = "PENDING"
    version: int = Field(default=1, ge=1)
    proposed_payload: EditorialOptions = Field(default_factory=EditorialOptions)
    evidence_snapshot: EvidenceSnapshot
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: AwareDatetime = Field(default_factory=now)
    updated_at: AwareDatetime = Field(default_factory=now)
    resolved_at: AwareDatetime | None = None
    human_decision: Literal["approve", "modify", "reject"] | None = None
    human_comment: str = Field(default="", max_length=500)
    approved_payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    result: FinalAnalysis | None = None

    @model_validator(mode="after")
    def integrity(self):
        r = self.evidence_snapshot.report
        if r.trace_id != self.trace_id or r.session_id != self.session_id:
            raise ValueError("Snapshot identity mismatch")
        if digest(self.evidence_snapshot) != self.snapshot_sha256:
            raise ValueError("Snapshot integrity failure")
        if self.updated_at < self.created_at:
            raise ValueError("Invalid timestamp order")
        terminal = self.status in ("EXECUTED", "REJECTED")
        if terminal != (self.resolved_at is not None):
            raise ValueError("Invalid resolution timestamp")
        if self.resolved_at and not self.created_at <= self.resolved_at <= self.updated_at:
            raise ValueError("Invalid resolution timestamp order")
        if (self.status == "EXECUTED") != (self.result is not None):
            raise ValueError("Only executed actions have a result")
        if self.status in ("APPROVED", "EXECUTED"):
            if self.human_decision != "approve" or self.approved_payload_sha256 != digest(
                self.proposed_payload
            ):
                raise ValueError("Approval does not authorize this proposal")
        if self.status == "REJECTED" and self.human_decision != "reject":
            raise ValueError("Missing rejection")
        if self.status == "MODIFIED" and (self.human_decision != "modify" or self.version < 2):
            raise ValueError("Modified proposal requires a recorded decision and new version")
        if self.status in ("PENDING", "MODIFIED", "REJECTED") and self.approved_payload_sha256:
            raise ValueError("Unapproved proposal cannot retain authorization")
        if self.result is not None:
            publication = self.result.publication
            if (
                not publication
                or publication.action_id != str(self.action_id)
                or publication.approved_version != self.version
                or publication.snapshot_sha256 != self.snapshot_sha256
                or publication.editorial != self.proposed_payload
                or self.result.model_dump(exclude={"publication"})
                != r.model_dump(exclude={"publication"})
            ):
                raise ValueError("Published report differs from approved evidence")
        return self

    def public(self) -> PendingActionResponse:
        r = self.evidence_snapshot.report
        return PendingActionResponse(
            action_id=str(self.action_id),
            status=self.status,
            version=self.version,
            summary=r.executive_summary,
            ticker=r.ticker,
            as_of=r.as_of,
            proposed_payload=self.proposed_payload,
            available_actions=["approve", "modify", "reject"]
            if self.status in ("PENDING", "MODIFIED")
            else [],
            trace_id=self.trace_id,
            session_id=self.session_id,
        )


class ActionDecisionResponse(Model):
    action: PendingActionResponse
    message: str
    result: FinalAnalysis | None = None


def finalize(action: PendingAction) -> FinalAnalysis:
    """No provider, tools, clock-dependent assessment or recomputation is allowed here."""
    action = PendingAction.model_validate(action.model_dump())
    if action.status != "APPROVED":
        raise ValueError("Approval required")
    result = action.evidence_snapshot.report.model_copy(deep=True)
    a = result.technical.assessment
    contents = {
        "overview": result.executive_summary,
        "trend": " ".join(
            a.signals[k].explanation
            for k in ("price_sma20", "price_sma50", "sma20_sma50", "ema12_ema26")
            if k in a.signals
        ),
        "momentum": " ".join(
            a.signals[k].explanation
            for k in ("rsi14", "macd_zero", "macd_signal", "macd_histogram")
            if k in a.signals
        ),
        "risk": " ".join([*a.conflicts, *a.warnings, *result.technical.limitations]),
    }
    options = action.proposed_payload
    ordered = [options.focus, *(s for s in options.include_sections if s != options.focus)]
    # Mandatory risk disclosure remains visible even when the editorial selection omits it.
    if "risk" not in ordered:
        ordered.append("risk")
    result.publication = ReportPublication(
        action_id=str(action.action_id),
        approved_version=action.version,
        snapshot_sha256=action.snapshot_sha256,
        editorial=options,
        sections={s: contents[s] for s in ordered},
    )
    return result
