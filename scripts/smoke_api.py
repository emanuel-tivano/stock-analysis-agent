"""Start real Uvicorn and exercise the web/API path against a local market stub."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from merval_agent.domain.policy import MARKET_TIMEZONE


def market_payload(symbol: str, history_range: str, sample_size: int = 60) -> dict:
    today = datetime.now(MARKET_TIMEZONE).date()
    rows = []
    for index in range(sample_size):
        close = 101 + index
        rows.append(
            {
                "date": str(today - timedelta(days=sample_size - 1 - index)),
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1000 + index,
                "currency": "peso_Argentino",
            }
        )
    return {
        "ok": True,
        "symbol": symbol,
        "market": "bCBA",
        "range": history_range,
        "fetchedAt": datetime.now(UTC).isoformat(),
        "meta": {"source": "live", "stale": False},
        "data": rows,
    }


class MarketStub(BaseHTTPRequestHandler):
    history_calls = 0
    sample_size = 60

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.endswith("/quote"):
            self.send_response(503)
            self.end_headers()
            return
        if "/api/stocks/" in parsed.path and parsed.path.endswith("/history"):
            type(self).history_calls += 1
            symbol = parsed.path.split("/")[-2]
            history_range = parse_qs(parsed.query).get("range", ["6M"])[0]
            body = json.dumps(
                market_payload(symbol, history_range, type(self).sample_size)
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    market = ThreadingHTTPServer(("127.0.0.1", 0), MarketStub)
    market_port = market.server_address[1]
    market_thread = threading.Thread(target=market.serve_forever, daemon=True)
    market_thread.start()
    with tempfile.TemporaryDirectory(prefix="merval-smoke-") as directory:
        env = {
            **os.environ,
            "DATABASE_PATH": str(Path(directory) / "smoke.sqlite3"),
            "LLM_PROVIDER": "fake",
            "MARKET_TRACKER_BASE_URL": f"http://127.0.0.1:{market_port}",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "merval_agent.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False
            ) as http:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        health = http.get("/health")
                        health.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Uvicorn failed to start") from None
                        time.sleep(0.1)
                assert health.json()["status"] == "ok"
                page = http.get("/")
                page.raise_for_status()
                assert "Stock Analysis Agent" in page.text
                asset = http.get("/assets/app.js")
                asset.raise_for_status()
                docs = http.get("/docs")
                docs.raise_for_status()
                for ticker in ("PPSA", "XYZINVALIDO"):
                    unsupported = http.post(
                        "/chat", json={"message": f"Analizá técnicamente {ticker}"}
                    )
                    unsupported.raise_for_status()
                    unsupported_body = unsupported.json()
                    assert unsupported_body["result_type"] == "asset_not_found"
                    assert unsupported_body["indicators"] == []
                    assert unsupported_body["technical_details"] is None
                assert MarketStub.history_calls == 0
                for ticker in ("GGAL", "PAMP"):
                    response = http.post(
                        "/chat",
                        json={
                            "message": f"Analizá técnicamente {ticker}",
                            "session_id": f"smoke-web-{ticker.lower()}",
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    assert body["status"] == "ANSWER"
                    assert body["ticker"] == ticker
                    assert body["confidence"]["label"] in (
                        "Alta",
                        "Media",
                        "Baja",
                        "No disponible",
                    )
                    assert " — " in body["rsi"]["summary"]
                    assert "MACD /" not in body["macd_summary"]
                    assert len(body["warnings"]) == len(set(body["warnings"]))
                    assert body["sources"]
                assert MarketStub.history_calls == 2
                MarketStub.sample_size = 10
                insufficient = http.post(
                    "/chat",
                    json={
                        "message": "Analizá técnicamente GGAL",
                        "session_id": "smoke-insufficient",
                    },
                )
                insufficient.raise_for_status()
                insufficient_body = insufficient.json()
                assert insufficient_body["result_type"] == "insufficient_market_data"
                assert insufficient_body["ticker"] == "GGAL"
                assert insufficient_body["technical_details"] is not None
                MarketStub.sample_size = 60
                legacy = http.post(
                    "/agent/run",
                    json={"message": "Analizá técnicamente GGAL", "session_id": "smoke-api"},
                )
                legacy.raise_for_status()
                legacy_body = legacy.json()
                assert legacy_body["status"] == "ANSWER"
                assert legacy_body["technical"]["assessment"]["warnings"]
                assert legacy_body["technical"]["assessment"]["signals"]["macd_zero"][
                    "explanation"
                ].startswith("MACD / cero")
                assert legacy_body["generation"]
                print(
                    "Uvicorn started; GET /, /health, /docs and asset=200; "
                    "PPSA/XYZINVALIDO=asset_not_found with 0 market calls; "
                    "GGAL/PAMP=ANSWER; short GGAL=insufficient_market_data; "
                    "POST /agent/run=200 ANSWER GGAL"
                )
        finally:
            process.terminate()
            process.wait(timeout=10)
            market.shutdown()
            market.server_close()
            market_thread.join(timeout=5)


if __name__ == "__main__":
    main()
