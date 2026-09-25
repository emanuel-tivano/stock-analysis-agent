import logging
from datetime import datetime
from typing import Literal

import httpx
from pydantic import AwareDatetime, TypeAdapter, ValidationError

from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import (
    Bar,
    HistoryRange,
    MarketHistory,
    Model,
    QuoteSnapshot,
    Ticker,
    now,
)
from merval_agent.domain.policy import MARKET_TIMEZONE
from merval_agent.domain.technical_assessment import stale_date

logger = logging.getLogger(__name__)


class InstrumentValidation(Model):
    status: Literal["VALIDATED", "NOT_FOUND", "UNSUPPORTED"]
    ticker: Ticker
    market: Literal["bCBA"]
    company_name: str | None = None
    classification: Literal["DOMESTIC_EQUITY_CANDIDATE", "CEDEAR", "EXCLUDED_INSTRUMENT"] | None = (
        None
    )
    classification_method: Literal["provider_description_policy"] | None = None
    source: str
    quote: QuoteSnapshot | None = None


def normalize_history(
    payload: dict,
    ticker: str,
    range: HistoryRange,
    source: str,
    *,
    received_at: datetime,
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

        rows = payload["data"]
        if not isinstance(rows, list):
            raise ValueError("Expected history rows")

        bars = []
        currencies = set()
        discarded = 0

        for row in rows:
            try:
                if not isinstance(row, dict):
                    raise ValueError("Expected history row object")

                bar = Bar.model_validate(
                    {k: row.get(k) if k == "volume" else row[k] for k in Bar.model_fields}
                )
            except (KeyError, TypeError, ValueError):
                discarded += 1
                continue

            bars.append(bar)
            currencies.add(row.get("currency"))

        if discarded:
            logger.warning(
                "Market Tracker discarded invalid history rows: received=%d valid=%d discarded=%d",
                len(rows),
                len(bars),
                discarded,
                extra={
                    "ticker": ticker,
                    "discarded_rows": discarded,
                    "valid_rows": len(bars),
                },
            )

        if not bars:
            raise ValueError("No valid history rows")

        meta = payload.get("meta", {})

        if not isinstance(meta, dict):
            raise ValueError("Expected metadata object")

        if "stale" in meta and not isinstance(meta["stale"], bool):
            raise ValueError("Expected boolean stale flag")

        if len(currencies) > 1:
            raise ValueError("Mixed currencies")

        return MarketHistory(
            ticker=ticker,
            range=range,
            bars=sorted(bars, key=lambda b: b.date),
            source=source,
            provider_fetched_at=TypeAdapter(AwareDatetime).validate_python(payload["fetchedAt"]),
            received_at=TypeAdapter(AwareDatetime).validate_python(received_at),
            mode=meta.get("source", "unknown"),
            stale=meta.get("stale", False),
            currency=next(iter(currencies), None),
            discarded_rows=discarded,
            resolved_variant=meta.get("resolvedVariant"),
        )

    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ExternalServiceError("Invalid Market Tracker response") from exc


def provider_fetched_timestamp(payload: dict) -> datetime | None:
    """Return the provider clock value without substituting a local timestamp."""
    value = payload.get("fetchedAt")
    if value is None:
        return None
    return TypeAdapter(AwareDatetime).validate_python(value)


def normalize_quote_bar(
    payload: dict,
    ticker: str,
    market: str = "bCBA",
) -> Bar:
    """Normalize prices; a quote is always provisional, never a verified daily close."""
    try:
        if not isinstance(payload, dict):
            raise ValueError("Expected quote JSON object")

        if payload.get("ok") is not True:
            raise ValueError("Upstream returned unsuccessful quote")

        if payload.get("symbol") != ticker:
            raise ValueError("Quote does not match requested asset")

        if payload.get("market") != market:
            raise ValueError("Quote does not match requested market")

        if payload.get("stale") is not False or payload.get("source") != "live":
            raise ValueError("Quote must be explicitly live and not stale")

        data = payload["data"]

        if not isinstance(data, dict):
            raise ValueError("Expected quote data object")

        if "symbol" in data and data["symbol"] != ticker:
            raise ValueError("Quote data does not match requested asset")

        if "market" in data and data["market"] != market:
            raise ValueError("Quote data does not match requested market")

        timestamp = quote_timestamp(data.get("timestamp"))

        return Bar.model_validate(
            {
                "date": timestamp.astimezone(MARKET_TIMEZONE).date(),
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "close": data["price"],
                "volume": data.get("volume"),
            }
        )

    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ExternalServiceError("Invalid Market Tracker quote response") from exc


def quote_timestamp(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Quote timestamp must be an ISO datetime with timezone")
    return TypeAdapter(AwareDatetime).validate_python(datetime.fromisoformat(value))


class ArgentinaMarketTrackerClient:
    def __init__(
        self,
        http: httpx.Client,
        base_url: str,
        *,
        enrich_quote: bool = True,
        stale_after_days: int = 7,
        clock=now,
        quote_policy: str = "include_provisional_ohlc",
    ):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.enrich_quote = enrich_quote
        self.stale_after_days = stale_after_days
        self.clock = clock
        if quote_policy not in ("include_provisional_ohlc", "history_only"):
            raise ValueError("Unsupported quote policy")
        self.quote_policy = quote_policy

    def get_quote(
        self,
        symbol: str,
        market: str = "bCBA",
    ) -> Bar:
        # Preserve the public price-only accessor; composition uses the full snapshot.
        return self._get_quote_snapshot(symbol, market).bar

    def validate_instrument(
        self,
        symbol: str,
        market: str = "bCBA",
    ) -> InstrumentValidation:
        """Validate a proposed local equity without treating provider failures as absence."""
        ticker = TypeAdapter(Ticker).validate_python(symbol)
        if market != "bCBA":
            raise ValueError("Only bCBA is supported")

        url = f"{self.base_url}/api/stocks/{ticker}/quote"
        try:
            response = self.http.get(url, params={"market": market})
            received_at = TypeAdapter(AwareDatetime).validate_python(self.clock())
            if response.status_code == 404:
                payload = response.json()
                if (
                    isinstance(payload, dict)
                    and payload.get("ok") is False
                    and payload.get("error") == "QUOTE_NOT_FOUND"
                ):
                    return InstrumentValidation(
                        status="NOT_FOUND",
                        ticker=ticker,
                        market="bCBA",
                        source=str(response.url),
                    )
                raise ValueError("Unexpected not-found response")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise ValueError("Expected successful quote response")
            if payload.get("symbol") != ticker or payload.get("market") != market:
                raise ValueError("Quote identity does not match proposal")
            if payload.get("source") != "live" or payload.get("stale") is not False:
                raise ValueError("Quote must be explicitly live and not stale")
            data = payload["data"]
            if not isinstance(data, dict):
                raise ValueError("Expected quote data object")
            if "symbol" in data and data["symbol"] != ticker:
                raise ValueError("Quote data does not match proposed symbol")
            if "market" in data and data["market"] != market:
                raise ValueError("Quote data does not match proposed market")
            description = data.get("description")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("Quote description is required for instrument identity")
            if data.get("currency") not in ("ARS", "peso_Argentino"):
                raise ValueError("Unexpected quote currency")
            # Existence validation does not turn this quote into analysis evidence. It still
            # verifies price coherence and a parseable provider timestamp.
            datetime.fromisoformat(data["timestamp"])
            Bar.model_validate(
                {
                    "date": received_at.astimezone(MARKET_TIMEZONE).date(),
                    "open": data["open"],
                    "high": data["high"],
                    "low": data["low"],
                    "close": data["price"],
                    "volume": data.get("volume"),
                }
            )
            description = description.strip()
            normalized_description = description.casefold()
            excluded_prefixes = (
                "bono ",
                "obligacion negociable ",
                "obligación negociable ",
                "letra ",
                "opcion ",
                "opción ",
                "futuro ",
                "indice ",
                "índice ",
                "fondo ",
                "etf ",
                "cripto ",
            )
            if normalized_description.startswith("cedear "):
                classification = "CEDEAR"
            elif normalized_description.startswith(excluded_prefixes):
                classification = "EXCLUDED_INSTRUMENT"
            else:
                classification = "DOMESTIC_EQUITY_CANDIDATE"
            quote = None
            try:
                bar = normalize_quote_bar(payload, ticker, market)
                observed_at = quote_timestamp(data.get("timestamp"))
                today = received_at.astimezone(MARKET_TIMEZONE).date()
                if observed_at > received_at or stale_date(bar.date, today, self.stale_after_days):
                    raise ValueError("Quote timestamp is future or too old")
                quote = QuoteSnapshot(
                    bar=bar,
                    source=str(response.url),
                    observed_at=observed_at,
                    provider_fetched_at=provider_fetched_timestamp(payload),
                    received_at=received_at,
                    currency=data.get("currency"),
                )
            except (ExternalServiceError, ValueError, ValidationError):
                # The listing is validated, but the quote remains ineligible as price evidence.
                quote = None
            return InstrumentValidation(
                status=(
                    "VALIDATED" if classification == "DOMESTIC_EQUITY_CANDIDATE" else "UNSUPPORTED"
                ),
                ticker=ticker,
                market="bCBA",
                company_name=description,
                classification=classification,
                classification_method="provider_description_policy",
                source=str(response.url),
                quote=quote,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ExternalServiceError("Market Tracker instrument validation unavailable") from exc

    def _get_quote_snapshot(self, symbol: str, market: str) -> QuoteSnapshot:
        ticker = TypeAdapter(Ticker).validate_python(symbol)

        if market != "bCBA":
            raise ValueError("Only bCBA is supported")

        url = f"{self.base_url}/api/stocks/{ticker}/quote"

        try:
            response = self.http.get(
                url,
                params={"market": market},
            )
            received_at = TypeAdapter(AwareDatetime).validate_python(self.clock())
            response.raise_for_status()

            payload = response.json()
            bar = normalize_quote_bar(payload, ticker, market)
            observed_at = quote_timestamp(payload["data"]["timestamp"])
            today = received_at.astimezone(MARKET_TIMEZONE).date()
            if observed_at > received_at or stale_date(bar.date, today, self.stale_after_days):
                raise ValueError("Quote timestamp is future or too old")
            return QuoteSnapshot(
                bar=bar,
                source=str(response.url),
                observed_at=observed_at,
                provider_fetched_at=provider_fetched_timestamp(payload),
                received_at=received_at,
                currency=payload["data"].get("currency"),
            )

        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise ExternalServiceError("Market Tracker quote unavailable or invalid") from exc

    def get_history(
        self,
        symbol: str,
        range: HistoryRange,
        market: str = "bCBA",
        validated_quote: QuoteSnapshot | None = None,
        quote_already_requested: bool = False,
    ) -> MarketHistory:
        ticker = TypeAdapter(Ticker).validate_python(symbol)
        range = TypeAdapter(HistoryRange).validate_python(range)

        if market != "bCBA":
            raise ValueError("Only bCBA is supported")

        url = f"{self.base_url}/api/stocks/{ticker}/history"

        try:
            response = self.http.get(
                url,
                params={"range": range, "market": market},
            )
            received_at = TypeAdapter(AwareDatetime).validate_python(self.clock())
            response.raise_for_status()

            history = normalize_history(
                response.json(),
                ticker,
                range,
                str(response.url),
                received_at=received_at,
            )

        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("Market Tracker unavailable or invalid JSON") from exc

        if not self.enrich_quote:
            return history
        # A quote cannot repair a stale/demo/unknown base or establish its currency.
        today = history.received_at.astimezone(MARKET_TIMEZONE).date()
        if (
            history.mode != "live"
            or history.stale
            or not history.currency
            or history.bars[-1].date > today
            or stale_date(history.bars[-1].date, today, self.stale_after_days)
        ):
            return history.model_copy(update={"enrichment_status": "ineligible_history"})
        if quote_already_requested and validated_quote is None:
            return history.model_copy(update={"enrichment_status": "unavailable"})
        # One optional request; no retry and no replacement of same-day history.
        try:
            quote = validated_quote or self._get_quote_snapshot(ticker, market)
            if quote.currency != history.currency:
                raise ExternalServiceError("Quote currency differs from history")
        except ExternalServiceError as exc:
            logger.warning(
                "Latest quote enrichment failed; keeping history",
                extra={
                    "ticker": ticker,
                    "reason": str(exc),
                },
            )
            return history.model_copy(update={"enrichment_status": "unavailable"})

        last_history_date = history.bars[-1].date

        if quote.bar.date <= last_history_date:
            return history.model_copy(update={"enrichment_status": "not_newer"})

        if self.quote_policy == "history_only":
            return MarketHistory.model_validate(
                {**history.model_dump(), "quote": quote, "enrichment_status": "excluded"}
            )

        logger.info(
            "Appending latest quote to market history",
            extra={
                "ticker": ticker,
                "history_last_date": str(last_history_date),
                "quote_date": str(quote.bar.date),
                "quote_close": quote.bar.close,
            },
        )

        return MarketHistory(
            ticker=history.ticker,
            range=history.range,
            bars=[*history.bars, quote.bar],
            source=history.source,
            provider_fetched_at=history.provider_fetched_at,
            received_at=history.received_at,
            mode=history.mode,
            stale=history.stale,
            currency=history.currency,
            discarded_rows=history.discarded_rows,
            resolved_variant=history.resolved_variant,
            quote=quote,
            enrichment_status="appended",
        )
