import sqlite3
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from starlette.requests import Request

from merval_agent.api.app import create_app
from merval_agent.api.rate_limit import client_key, protected_bucket
from merval_agent.config import Settings
from merval_agent.memory.sqlite import SQLiteRepository


class MutableClock:
    def __init__(self, value=1_800_000_010.0):
        self.value = value

    def __call__(self):
        return self.value


class CountingProvider:
    def __init__(self, provider):
        self.provider = provider
        self.calls = 0

    def decide(self, state, tools):
        self.calls += 1
        return self.provider.decide(state, tools)


def settings(**changes):
    return Settings(
        _env_file=None,
        rate_limit_chat_per_minute=1,
        rate_limit_agent_run_per_minute=1,
        rate_limit_hitl_per_minute=1,
        **changes,
    )


def request_with(*, peer="192.0.2.10", headers=()):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
            "client": (peer, 1234),
        }
    )


def analyses(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT count(*) FROM analyses").fetchone()[0]


def test_blocked_agent_run_is_clean_and_skips_all_expensive_work(make_agent, tmp_path):
    agent, repo = make_agent()
    agent.provider = CountingProvider(agent.provider)
    path = str(tmp_path / "limited.sqlite3")
    agent.repository = SQLiteRepository(path)
    clock = MutableClock()

    with TestClient(
        create_app(agent, settings(), rate_limit_clock=clock), raise_server_exceptions=False
    ) as client:
        allowed = client.post("/agent/run", json={"message": "Técnico GGAL"})
        provider_calls = agent.provider.calls
        market_calls = list(repo.market_paths)
        blocked = client.post("/agent/run", json={"message": "Técnico GGAL"})

    assert allowed.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json() == {
        "detail": "Demasiadas solicitudes. Intentá nuevamente en unos segundos."
    }
    assert blocked.headers["retry-after"] == "50"
    assert "charset=utf-8" in blocked.headers["content-type"]
    assert blocked.headers["x-content-type-options"] == "nosniff"
    assert blocked.headers["referrer-policy"] == "no-referrer"
    assert agent.provider.calls == provider_calls
    assert repo.market_paths == market_calls
    assert analyses(path) == 1


def test_new_window_allows_requests_again(make_agent, tmp_path):
    agent, _ = make_agent()
    path = str(tmp_path / "window.sqlite3")
    agent.repository = SQLiteRepository(path)
    clock = MutableClock()

    with TestClient(create_app(agent, settings(), rate_limit_clock=clock)) as client:
        assert client.post("/agent/run", json={"message": "GGAL"}).status_code == 200
        assert client.post("/agent/run", json={"message": "GGAL"}).status_code == 429
        clock.value += 60
        assert client.post("/agent/run", json={"message": "GGAL"}).status_code == 200

    assert analyses(path) == 2


def test_clients_and_expensive_routes_have_independent_buckets(make_agent):
    agent, _ = make_agent()
    headers_a = {"x-vercel-forwarded-for": "198.51.100.10"}
    headers_b = {"x-vercel-forwarded-for": "198.51.100.11"}

    with TestClient(
        create_app(agent, settings(), trust_vercel_headers=True)
    ) as client:
        assert client.post("/agent/run", json={"message": "XXXX"}, headers=headers_a).status_code == 200
        assert client.post("/chat", json={"message": "XXXX"}, headers=headers_a).status_code == 200
        assert client.post("/agent/run", json={"message": "XXXX"}, headers=headers_a).status_code == 429
        assert client.post("/chat", json={"message": "XXXX"}, headers=headers_a).status_code == 429
        assert client.post("/agent/run", json={"message": "XXXX"}, headers=headers_b).status_code == 200


def test_disabled_rate_limit_preserves_current_behavior(make_agent):
    agent, repo = make_agent()
    with TestClient(create_app(agent, settings(rate_limit_enabled=False))) as client:
        assert client.post("/agent/run", json={"message": "XXXX"}).status_code == 200
        assert client.post("/agent/run", json={"message": "XXXX"}).status_code == 200
    assert len(repo.records) == 2


def test_health_root_assets_and_hitl_reads_are_not_limited(make_agent):
    agent, _ = make_agent()
    with TestClient(create_app(agent, settings())) as client:
        for _ in range(3):
            assert client.get("/health").status_code == 200
            assert client.get("/").status_code == 200
            assert client.get("/assets/styles.css").status_code == 200


def test_hitl_limit_is_before_decision_and_preserves_idempotent_replay(
    make_agent, tmp_path
):
    agent, _ = make_agent()
    path = str(tmp_path / "hitl-limited.sqlite3")
    agent.repository = SQLiteRepository(path)
    clock = MutableClock()

    with TestClient(create_app(agent, settings(), rate_limit_clock=clock)) as client:
        paused = client.post(
            "/agent/run",
            json={
                "message": "Prepará un informe técnico de GGAL para revisión.",
                "session_id": "limited-hitl",
            },
        ).json()
        action = paused["pending_action"]
        endpoint = f"/agent/actions/{action['action_id']}/approve"
        body = {
            "session_id": "limited-hitl",
            "expected_version": action["version"],
            "idempotency_key": "rate-limit-idempotency-key",
        }
        approved = client.post(endpoint, json=body)
        blocked = client.post(endpoint, json=body)
        with sqlite3.connect(path) as db:
            publications_while_blocked = db.execute(
                "SELECT count(*) FROM report_publications"
            ).fetchone()[0]
            decisions_while_blocked = db.execute(
                "SELECT count(*) FROM action_decisions"
            ).fetchone()[0]
        clock.value += 60
        replay = client.post(endpoint, json=body)

    assert approved.status_code == 200
    assert blocked.status_code == 429
    assert publications_while_blocked == decisions_while_blocked == 1
    assert replay.status_code == 200
    assert replay.json() == approved.json()


def test_sqlite_consumption_is_atomic_under_concurrency(tmp_path):
    path = str(tmp_path / "concurrent.sqlite3")
    SQLiteRepository(path)

    def consume(_):
        repository = SQLiteRepository(path)
        return repository.consume_rate_limit("client", "chat", 1_800_000_000, 3, 1_800_000_000)

    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(consume, range(20)))

    assert sum(outcomes) == 3
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT request_count FROM rate_limit_buckets").fetchone()[0] == 3


def test_client_identity_uses_only_trusted_single_vercel_ip_and_never_logs_it(caplog):
    peer_only = client_key(request_with(), trust_vercel_headers=False)
    spoofed = client_key(
        request_with(headers=(("x-forwarded-for", "203.0.113.9"),)),
        trust_vercel_headers=False,
    )
    trusted = client_key(
        request_with(headers=(("x-vercel-forwarded-for", "203.0.113.9"),)),
        trust_vercel_headers=True,
    )
    multiple = client_key(
        request_with(headers=(("x-vercel-forwarded-for", "203.0.113.9, 10.0.0.1"),)),
        trust_vercel_headers=True,
    )
    malformed = client_key(
        request_with(peer="bad peer value", headers=(("x-vercel-forwarded-for", "not-an-ip"),)),
        trust_vercel_headers=True,
    )

    assert peer_only == spoofed == multiple
    assert trusted != peer_only
    assert len(trusted) == len(malformed) == 64
    assert "203.0.113.9" not in trusted
    assert "203.0.113.9" not in caplog.text


def test_route_mapping_covers_all_decisions_and_rejects_unprotected_methods():
    for decision in ("approve", "modify", "reject"):
        assert protected_bucket("POST", f"/agent/actions/id/{decision}") == "hitl"
    assert protected_bucket("GET", "/agent/actions/id") is None
    assert protected_bucket("POST", "/health") is None


def test_openapi_documents_429_only_on_protected_operations(make_agent):
    agent, _ = make_agent()
    with TestClient(create_app(agent, settings())) as client:
        schema = client.get("/openapi.json").json()

    protected = [
        "/chat",
        "/agent/run",
        "/agent/actions/{action_id}/approve",
        "/agent/actions/{action_id}/modify",
        "/agent/actions/{action_id}/reject",
    ]
    for path in protected:
        assert "429" in schema["paths"][path]["post"]["responses"]
    assert "429" not in schema["paths"]["/health"]["get"]["responses"]
