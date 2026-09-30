import pytest

import app as vercel_entrypoint
import merval_agent.bootstrap as bootstrap
from merval_agent.api.app import app as api_app
from merval_agent.config import Settings
from merval_agent.memory.postgres import PostgresRepository
from scripts.bootstrap_postgres import DATABASE, ROLE, upsert_env


class FakeConnection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        return self


def test_vercel_entrypoint_exports_fastapi_application():
    assert vercel_entrypoint.app is api_app


def test_repository_factory_keeps_sqlite_as_local_default(monkeypatch, tmp_path):
    expected = object()
    monkeypatch.setattr(bootstrap, "SQLiteRepository", lambda path: expected)
    settings = Settings(_env_file=None, database_path=str(tmp_path / "local.sqlite3"))
    assert bootstrap.build_repository(settings) is expected


def test_repository_factory_selects_postgres_without_exposing_url(monkeypatch):
    captured = []
    expected = object()

    def build(url):
        captured.append(url)
        return expected

    monkeypatch.setattr(bootstrap, "PostgresRepository", build)
    settings = Settings(_env_file=None, database_url="postgresql://user:secret@db.example/tfi")
    assert bootstrap.build_repository(settings) is expected
    assert captured == ["postgresql://user:secret@db.example/tfi"]
    assert "secret" not in repr(settings.database_url)


def test_postgres_repository_serializes_schema_migration():
    connection = FakeConnection()
    calls = []

    def connect(url, **options):
        calls.append((url, options))
        return connection

    PostgresRepository("postgresql://db.example/tfi", connect=connect)

    assert calls == [
        (
            "postgresql://db.example/tfi",
            {"connect_timeout": 10, "application_name": "merval-equity-agent"},
        )
    ]
    sql = "\n".join(statement for statement, _ in connection.statements)
    assert "pg_advisory_xact_lock" in sql
    assert "CREATE TABLE IF NOT EXISTS analyses" in sql
    assert "CREATE TABLE IF NOT EXISTS pending_actions" in sql
    assert "CREATE TABLE IF NOT EXISTS action_decisions" in sql
    assert "CREATE TABLE IF NOT EXISTS report_publications" in sql
    assert sql.index("pg_advisory_xact_lock") < sql.index("CREATE TABLE")


def test_postgres_repository_rejects_non_postgres_urls():
    with pytest.raises(ValueError, match="PostgreSQL protocol"):
        PostgresRepository("sqlite:///tmp/not-production.sqlite3")


def test_postgres_bootstrap_updates_only_requested_env_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_API_KEY=keep-me\nTEST_DATABASE_URL=old\n", encoding="utf-8")

    upsert_env(env_file, "TEST_DATABASE_URL", "postgresql://new")

    assert env_file.read_text(encoding="utf-8") == (
        "LLM_API_KEY=keep-me\nTEST_DATABASE_URL=postgresql://new\n"
    )


def test_postgres_bootstrap_identifiers_are_fixed():
    assert ROLE == "merval_agent_test"
    assert DATABASE == "merval_agent_test"
