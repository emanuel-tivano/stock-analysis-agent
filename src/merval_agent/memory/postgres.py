"""Durable PostgreSQL repository for serverless production deployments."""

import hashlib
import json
from collections.abc import Callable

import psycopg

from merval_agent.domain.actions import (
    ActionDecisionResponse,
    ApproveActionRequest,
    ModifyActionRequest,
    PendingAction,
    canonical,
    digest,
    finalize,
)
from merval_agent.domain.models import AgentState, FinalAnalysis, now
from merval_agent.memory.actions import ActionConflict, ActionNotFound, action_message

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS analyses (
        trace_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        ticker TEXT,
        user_request TEXT NOT NULL,
        final_status TEXT NOT NULL,
        tool_trace TEXT NOT NULL,
        summary TEXT NOT NULL,
        events TEXT NOT NULL DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS pending_actions (
        action_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL UNIQUE REFERENCES analyses(trace_id),
        session_id TEXT NOT NULL,
        status TEXT NOT NULL,
        version INTEGER NOT NULL,
        document TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS actions_session ON pending_actions(session_id)",
    """CREATE TABLE IF NOT EXISTS action_events (
        event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        action_id TEXT NOT NULL REFERENCES pending_actions(action_id),
        event TEXT NOT NULL,
        proposal TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS events_action ON action_events(action_id, event_id)",
    """CREATE TABLE IF NOT EXISTS action_decisions (
        action_id TEXT NOT NULL REFERENCES pending_actions(action_id),
        key_hash TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        response TEXT NOT NULL,
        PRIMARY KEY(action_id, key_hash)
    )""",
    """CREATE TABLE IF NOT EXISTS report_publications (
        action_id TEXT PRIMARY KEY REFERENCES pending_actions(action_id),
        trace_id TEXT NOT NULL UNIQUE REFERENCES analyses(trace_id),
        result TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )""",
)


class PostgresRepository:
    """Persist traces and HITL transitions outside ephemeral function instances."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[..., psycopg.Connection] = psycopg.connect,
    ):
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must use the PostgreSQL protocol")
        self.database_url = database_url
        self._connect = connect
        self._migrate()

    def _connection(self):
        return self._connect(
            self.database_url,
            connect_timeout=10,
            application_name="merval-equity-agent",
        )

    def _migrate(self) -> None:
        with self._connection() as db:
            # Serialize schema setup when several serverless instances start together.
            db.execute("SELECT pg_advisory_xact_lock(%s)", (730_124_526_2026,))
            for statement in SCHEMA_STATEMENTS:
                db.execute(statement)
            db.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (%s, %s) "
                "ON CONFLICT (version) DO NOTHING",
                (1, now().isoformat()),
            )

    @staticmethod
    def _tool_trace(state: AgentState) -> list[dict]:
        return [
            {
                "step": event["step"],
                "tool": event["tool_name"],
                "success": event["event"] == "TOOL_SUCCEEDED",
                "latency_ms": event["latency_ms"],
                "error": event["error"],
            }
            for event in state.trace_events
            if event["event"] in ("TOOL_SUCCEEDED", "TOOL_FAILED")
        ]

    def save(
        self,
        state: AgentState,
        result: FinalAnalysis,
        *,
        pending_action: PendingAction | None = None,
    ) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT INTO analyses "
                "(trace_id, session_id, timestamp, ticker, user_request, final_status, "
                "tool_trace, summary, events) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    state.trace_id,
                    state.session_id,
                    now().isoformat(),
                    result.ticker,
                    state.user_request,
                    result.status,
                    json.dumps(self._tool_trace(state)),
                    result.executive_summary,
                    json.dumps(state.trace_events),
                ),
            )
            if pending_action is not None:
                self._insert_action(db, pending_action)

    def _insert_action(self, db, action: PendingAction) -> None:
        action = PendingAction.model_validate(action.model_dump())
        if action.status != "PENDING":
            raise ValueError("New actions must be pending")
        db.execute(
            "INSERT INTO pending_actions "
            "(action_id, trace_id, session_id, status, version, document) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                str(action.action_id),
                action.trace_id,
                action.session_id,
                action.status,
                action.version,
                action.model_dump_json(),
            ),
        )
        self._action_event(db, action, "ACTION_PROPOSED", "NONE")
        self._action_event(
            db,
            action,
            "ACTION_PAUSED",
            "PENDING",
            reason="HUMAN_REVIEW_REQUIRED",
        )

    @staticmethod
    def _read_action(db, action_id, session_id, *, for_update=False) -> PendingAction:
        locking = " FOR UPDATE" if for_update else ""
        row = db.execute(
            "SELECT document,status,version,trace_id,session_id FROM pending_actions "
            "WHERE action_id=%s AND session_id=%s" + locking,
            (str(action_id), session_id),
        ).fetchone()
        if row is None:
            raise ActionNotFound
        try:
            action = PendingAction.model_validate_json(row[0])
            if (action.status, action.version, action.trace_id, action.session_id) != tuple(row[1:]):
                raise ValueError("Index mismatch")
            if str(action.action_id) != str(action_id):
                raise ValueError("Identity mismatch")
            return action
        except ValueError:
            raise ActionConflict("No se pudo verificar la integridad de la acción.") from None

    @staticmethod
    def _action_event(
        db,
        action: PendingAction,
        name: str,
        previous: str,
        *,
        actor="system",
        key_hash=None,
        reason="PROPOSED",
    ) -> None:
        record = {
            "event": name,
            "action_id": str(action.action_id),
            "trace_id": action.trace_id,
            "session_id": action.session_id,
            "version": action.version,
            "transition": f"{previous}->{action.status}",
            "timestamp": action.updated_at.isoformat(),
            "outcome": "CONFLICT" if name == "ACTION_CONFLICT" else action.status,
            "actor": actor,
            "reason": reason,
            "payload_sha256": digest(action.proposed_payload),
            "idempotency_key_sha256": key_hash,
        }
        db.execute(
            "INSERT INTO action_events(action_id,event,proposal) VALUES (%s,%s,%s)",
            (str(action.action_id), canonical(record), canonical(action.proposed_payload)),
        )
        row = db.execute(
            "SELECT events FROM analyses WHERE trace_id=%s FOR UPDATE", (action.trace_id,)
        ).fetchone()
        if row is None:
            raise ActionConflict("No se encontró la traza asociada a la acción.")
        events = json.loads(row[0])
        events.append(record)
        db.execute(
            "UPDATE analyses SET events=%s WHERE trace_id=%s",
            (json.dumps(events), action.trace_id),
        )

    def get_action(self, action_id, session_id):
        with self._connection() as db:
            action = self._read_action(db, action_id, session_id)
            return ActionDecisionResponse(
                action=action.public(),
                result=action.result,
                message=action_message(action),
            )

    def decide_action(self, action_id, decision: str, request: ApproveActionRequest):
        if decision not in ("approve", "modify", "reject"):
            raise ValueError("Unsupported decision")
        if decision == "modify" and not isinstance(request, ModifyActionRequest):
            raise ValueError("Editorial options required")

        key_hash = hashlib.sha256(request.idempotency_key.encode()).hexdigest()
        request_hash = digest({"decision": decision, "request": request.model_dump(mode="json")})
        conflict = None
        response = None
        with self._connection() as db:
            action = self._read_action(db, action_id, request.session_id, for_update=True)
            saved = db.execute(
                "SELECT request_hash,response FROM action_decisions "
                "WHERE action_id=%s AND key_hash=%s",
                (str(action_id), key_hash),
            ).fetchone()
            if saved and saved[0] == request_hash:
                return ActionDecisionResponse.model_validate_json(saved[1])
            if saved:
                conflict = "La clave de idempotencia ya se usó con otra decisión."
            elif action.version != request.expected_version:
                conflict = "La propuesta cambió. Recuperá la versión actual antes de decidir."
            elif action.status not in ("PENDING", "MODIFIED"):
                conflict = "La acción ya fue resuelta; no puede modificarse ni ejecutarse otra vez."

            if conflict:
                action.updated_at = now()
                self._action_event(
                    db,
                    action,
                    "ACTION_CONFLICT",
                    action.status,
                    actor="human",
                    key_hash=key_hash,
                    reason="VERSION_STATE_OR_KEY_CONFLICT",
                )
            else:
                previous = action.status
                action.updated_at = now()
                action.human_decision = decision
                action.human_comment = request.comment
                if decision == "modify":
                    action.version += 1
                    action.proposed_payload = request.changes.model_copy(deep=True)
                    action.status = "MODIFIED"
                    self._action_event(
                        db,
                        action,
                        "ACTION_MODIFIED",
                        previous,
                        actor="human",
                        key_hash=key_hash,
                        reason="EDITORIAL_CHANGE",
                    )
                    message = "Propuesta modificada; todavía requiere aprobación."
                elif decision == "reject":
                    action.status = "REJECTED"
                    action.resolved_at = action.updated_at
                    self._action_event(
                        db,
                        action,
                        "ACTION_REJECTED",
                        previous,
                        actor="human",
                        key_hash=key_hash,
                        reason="HUMAN_REJECTION",
                    )
                    message = "Informe rechazado. No se publicó; la auditoría se conserva."
                else:
                    action.status = "APPROVED"
                    action.approved_payload_sha256 = digest(action.proposed_payload)
                    self._action_event(
                        db,
                        action,
                        "ACTION_APPROVED",
                        previous,
                        actor="human",
                        key_hash=key_hash,
                        reason="EXACT_VERSION_APPROVAL",
                    )
                    action.result = finalize(action)
                    db.execute(
                        "INSERT INTO report_publications(action_id,trace_id,result) "
                        "VALUES (%s,%s,%s)",
                        (str(action_id), action.trace_id, action.result.model_dump_json()),
                    )
                    action.status = "EXECUTED"
                    action.resolved_at = action.updated_at
                    self._action_event(
                        db,
                        action,
                        "ACTION_EXECUTED",
                        "APPROVED",
                        key_hash=key_hash,
                        reason="LOCAL_REPORT_FINALIZED",
                    )
                    message = "Informe finalizado con la evidencia guardada, sin nuevas consultas."

                action = PendingAction.model_validate(action.model_dump())
                updated = db.execute(
                    "UPDATE pending_actions SET status=%s,version=%s,document=%s "
                    "WHERE action_id=%s AND version=%s AND status=%s",
                    (
                        action.status,
                        action.version,
                        action.model_dump_json(),
                        str(action_id),
                        request.expected_version,
                        previous,
                    ),
                )
                if updated.rowcount != 1:
                    raise ActionConflict("La propuesta cambió durante la decisión.")
                response = ActionDecisionResponse(
                    action=action.public(), message=message, result=action.result
                )
                db.execute(
                    "INSERT INTO action_decisions "
                    "(action_id,key_hash,request_hash,response) VALUES (%s,%s,%s,%s)",
                    (str(action_id), key_hash, request_hash, response.model_dump_json()),
                )
                db.execute(
                    "UPDATE analyses SET final_status=%s WHERE trace_id=%s",
                    (
                        "ANSWER"
                        if action.result
                        else "REJECTED"
                        if decision == "reject"
                        else "PAUSED",
                        action.trace_id,
                    ),
                )
                if action.result:
                    db.execute(
                        "UPDATE analyses SET summary=%s WHERE trace_id=%s",
                        (action.result.executive_summary, action.trace_id),
                    )

        if conflict:
            raise ActionConflict(conflict)
        return response

    def get_action_events(self, action_id, session_id):
        with self._connection() as db:
            self._read_action(db, action_id, session_id)
            rows = db.execute(
                "SELECT event FROM action_events WHERE action_id=%s ORDER BY event_id",
                (str(action_id),),
            )
            return [json.loads(row[0]) for row in rows]

    def get_trace(self, trace_id: str) -> dict | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT trace_id,session_id,timestamp,ticker,final_status,tool_trace,events "
                "FROM analyses WHERE trace_id=%s",
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(
            zip(
                (
                    "trace_id",
                    "session_id",
                    "timestamp",
                    "ticker",
                    "final_status",
                    "tool_trace",
                    "events",
                ),
                row,
                strict=True,
            )
        )
        for key in ("tool_trace", "events"):
            result[key] = json.loads(result[key])
        return result
