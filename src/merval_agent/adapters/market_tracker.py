import httpx
from pydantic import TypeAdapter, ValidationError

from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import Bar, HistoryRange, MarketHistory, Ticker


def normalize_history(
    payload: dict, ticker: str, range: HistoryRange, source: str
) -> MarketHistory:
    """Contract verified against the public endpoint on 2026-09-15."""
    try:
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object")
        if payload.get("ok") is not True:
            raise ValueError("Upstream returned unsuccessful response")
        if payload.get("symbol") != ticker or payload.get("range") != range:
            raise ValueError("Response does not match requested asset/range")
        if payload.get("market") != "bCBA":
            raise ValueError("Unexpected market")
        bars = [
            Bar.model_validate({k: row[k] for k in Bar.model_fields}) for row in payload["data"]
        ]
        meta = payload.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError("Expected metadata object")
        if "stale" in meta and not isinstance(meta["stale"], bool):
            raise ValueError("Expected boolean stale flag")
        currencies = {row.get("currency") for row in payload["data"]}
        if len(currencies) > 1:
            raise ValueError("Mixed currencies")
        return MarketHistory(
            ticker=ticker,
            range=range,
            bars=sorted(bars, key=lambda b: b.date),
            source=source,
            fetched_at=payload["fetchedAt"],
            mode=meta.get("source", "unknown"),
            stale=meta.get("stale", False),
            currency=next(iter(currencies), None),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ExternalServiceError("Invalid Market Tracker response") from exc


class ArgentinaMarketTrackerClient:
    def __init__(self, http: httpx.Client, base_url: str):
        self.http = http
        self.base_url = base_url.rstrip("/")

    def get_history(self, symbol: str, range: HistoryRange, market: str = "bCBA") -> MarketHistory:
        ticker = TypeAdapter(Ticker).validate_python(symbol)
        range = TypeAdapter(HistoryRange).validate_python(range)
        if market != "bCBA":
            raise ValueError("Only bCBA is supported")
        url = f"{self.base_url}/api/stocks/{ticker}/history"
        try:
            response = self.http.get(url, params={"range": range, "market": market})
            response.raise_for_status()
            return normalize_history(response.json(), ticker, range, str(response.url))
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("Market Tracker unavailable or invalid JSON") from exc

    def get_quote(self, symbol: str):
        raise NotImplementedError("Quote endpoint contract has not been verified")
