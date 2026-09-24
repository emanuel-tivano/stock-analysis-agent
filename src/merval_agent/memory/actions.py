"""SQLite serialization is the concurrency boundary, including result publication."""

import hashlib
import json
import sqlite3
from contextlib import closing

from merval_agent.domain.actions import (
    ActionDecisionResponse,
    ApproveActionRequest,
    ModifyActionRequest,
    PendingAction,
    canonical,
    digest,
    finalize,
)
from merval_agent.domain.models import now


class ActionNotFound(Exception):
    pass


class ActionConflict(Exception):
    pass


def migrate_actions(db):
    db.execute("""CREATE TABLE IF NOT EXISTS pending_actions (
        action_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL UNIQUE REFERENCES analyses(trace_id),
        session_id TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL,
        document TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS actions_session ON pending_actions(session_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS action_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id TEXT NOT NULL REFERENCES pending_actions(action_id),
        event TEXT NOT NULL, proposal TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS events_action ON action_events(action_id, event_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS action_decisions (
        action_id TEXT NOT NULL REFERENCES pending_actions(action_id), key_hash TEXT NOT NULL,
        request_hash TEXT NOT NULL, response TEXT NOT NULL,
        PRIMARY KEY(action_id, key_hash))""")
    db.execute("""CREATE TABLE IF NOT EXISTS report_publications (
        action_id TEXT PRIMARY KEY REFERENCES pending_actions(action_id),
        trace_id TEXT NOT NULL UNIQUE REFERENCES analyses(trace_id), result TEXT NOT NULL)""")


def action_event(db, action, name, previous, *, actor="system", key_hash=None, reason="PROPOSED"):
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
        "INSERT INTO action_events(action_id,event,proposal) VALUES (?,?,?)",
        (str(action.action_id), canonical(record), canonical(action.proposed_payload)),
    )
    row = db.execute("SELECT events FROM analyses WHERE trace_id=?", (action.trace_id,)).fetchone()
    events = json.loads(row[0])
    events.append(record)
    db.execute(
        "UPDATE analyses SET events=? WHERE trace_id=?", (json.dumps(events), action.trace_id)
    )


def insert_action(db, action):
    action = PendingAction.model_validate(action.model_dump())
    if action.status != "PENDING":
        raise ValueError("New actions must be pending")
    db.execute(
        "INSERT INTO pending_actions VALUES (?,?,?,?,?,?)",
        (
            str(action.action_id),
            action.trace_id,
            action.session_id,
            action.status,
            action.version,
            action.model_dump_json(),
        ),
    )
    action_event(db, action, "ACTION_PROPOSED", "NONE")
    action_event(db, action, "ACTION_PAUSED", "PENDING", reason="HUMAN_REVIEW_REQUIRED")


class ActionStore:
    # SQLiteRepository supplies path. Every call uses its own connection: no process-local lock.
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _read_action(db, action_id, session_id):
        row = db.execute(
            "SELECT document,status,version,trace_id,session_id FROM pending_actions WHERE action_id=? AND session_id=?",
            (str(action_id), session_id),
        ).fetchone()
        if row is None:
            raise ActionNotFound
        try:
            action = PendingAction.model_validate_json(row[0])
            if (action.status, action.version, action.trace_id, action.session_id) != tuple(
                row[1:]
            ):
                raise ValueError("Index mismatch")
            if str(action.action_id) != str(action_id):
                raise ValueError("Identity mismatch")
            return action
        except ValueError:
            raise ActionConflict("No se pudo verificar la integridad de la acción.") from None

    def get_action(self, action_id, session_id):
        with closing(self._connection()) as db:
            action = self._read_action(db, action_id, session_id)
            return ActionDecisionResponse(
                action=action.public(),
                result=action.result,
                message="Informe finalizado." if action.result else "Acción " + action.status + ".",
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
        with closing(self._connection()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            action = self._read_action(db, action_id, request.session_id)
            saved = db.execute(
                "SELECT request_hash,response FROM action_decisions WHERE action_id=? AND key_hash=?",
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
                action_event(
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
                    action_event(
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
                    action_event(
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
                    action_event(
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
                        "INSERT INTO report_publications(action_id,trace_id,result) VALUES (?,?,?)",
                        (str(action_id), action.trace_id, action.result.model_dump_json()),
                    )
                    action.status = "EXECUTED"
                    action.resolved_at = action.updated_at
                    action_event(
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
                    "UPDATE pending_actions SET status=?,version=?,document=? WHERE action_id=? AND version=? AND status=?",
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
                    "INSERT INTO action_decisions VALUES (?,?,?,?)",
                    (str(action_id), key_hash, request_hash, response.model_dump_json()),
                )
                db.execute(
                    "UPDATE analyses SET final_status=? WHERE trace_id=?",
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
                        "UPDATE analyses SET summary=? WHERE trace_id=?",
                        (action.result.executive_summary, action.trace_id),
                    )
        if conflict:
            raise ActionConflict(conflict)
        return response

    def get_action_events(self, action_id, session_id):
        with closing(self._connection()) as db:
            self._read_action(db, action_id, session_id)
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT event FROM action_events WHERE action_id=? ORDER BY event_id",
                    (str(action_id),),
                )
            ]
