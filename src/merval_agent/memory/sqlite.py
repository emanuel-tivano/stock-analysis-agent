import json
import sqlite3
from contextlib import closing
from pathlib import Path

from merval_agent.domain.models import AgentState, FinalAnalysis, now
from merval_agent.memory.actions import ActionStore, insert_action, migrate_actions


class SQLiteRepository(ActionStore):
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS analyses (
                trace_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                ticker TEXT, user_request TEXT NOT NULL, final_status TEXT NOT NULL,
                tool_trace TEXT NOT NULL, summary TEXT NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(analyses)")}
            if "events" not in columns:
                db.execute("ALTER TABLE analyses ADD COLUMN events TEXT NOT NULL DEFAULT '[]'")
            migrate_actions(db)

    def save(self, state: AgentState, result: FinalAnalysis, *, pending_action=None) -> None:
        trace = []
        for event in state.trace_events:
            if event["event"] in ("TOOL_SUCCEEDED", "TOOL_FAILED"):
                trace.append(
                    {
                        "step": event["step"],
                        "tool": event["tool_name"],
                        "success": event["event"] == "TOOL_SUCCEEDED",
                        "latency_ms": event["latency_ms"],
                        "error": event["error"],
                    }
                )
        with closing(self._connection()) as db, db:
            db.execute(
                "INSERT INTO analyses "
                "(trace_id, session_id, timestamp, ticker, user_request, final_status, "
                "tool_trace, summary, events) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    state.trace_id,
                    state.session_id,
                    now().isoformat(),
                    result.ticker,
                    state.user_request,
                    result.status,
                    json.dumps(trace),
                    result.executive_summary,
                    json.dumps(state.trace_events),
                ),
            )
            if pending_action is not None:
                insert_action(db, pending_action)

    def get_trace(self, trace_id: str) -> dict | None:
        """Read persisted events without returning the private request or free-text summary."""
        return read_trace(self.path, trace_id)


def read_trace(path: str, trace_id: str) -> dict | None:
    # Read-only: inspecting a typo must not create a database or migrate an old one.
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute("PRAGMA table_info(analyses)")}
        event_column = "events" if "events" in columns else "'[]' AS events"
        row = db.execute(
            "SELECT trace_id, session_id, timestamp, ticker, final_status, tool_trace, "
            + event_column
            + " FROM analyses WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    for key in ("tool_trace", "events"):
        result[key] = json.loads(result[key])
    return result
