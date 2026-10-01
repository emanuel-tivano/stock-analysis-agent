import sqlite3

from merval_agent.memory.sqlite import SQLiteRepository


def test_migrate_old_database(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE analyses(trace_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
            "timestamp TEXT NOT NULL,ticker TEXT,user_request TEXT NOT NULL,"
            "final_status TEXT NOT NULL,tool_trace TEXT NOT NULL,summary TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO analyses VALUES "
            "('old','s','date','GGAL','private','ANSWER','[]','summary')"
        )
    repo = SQLiteRepository(path)
    assert repo.get_trace("old")["final_status"] == "ANSWER"
    SQLiteRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM pending_actions").fetchone()[0] == 0
