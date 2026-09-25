import re
from collections.abc import Callable

from merval_agent.adapters.bolsar_parser import folded
from merval_agent.adapters.market_tracker import InstrumentValidation
from merval_agent.domain.models import TICKER_PATTERN, AssetResolution, CompanyType

CATALOG = {
    "GGAL": ("Grupo Financiero Galicia", CompanyType.FINANCIAL, ["galicia"]),
    "BMA": ("Banco Macro", CompanyType.FINANCIAL, ["macro"]),
    "SUPV": ("Grupo Supervielle", CompanyType.FINANCIAL, ["supervielle"]),
    "PAMP": ("Pampa Energía", CompanyType.ENERGY, ["pampa"]),
    "YPFD": ("YPF", CompanyType.ENERGY, ["ypf"]),
    "ALUA": ("Aluar", CompanyType.INDUSTRIAL, ["aluar"]),
    "TRAN": ("Transener", CompanyType.UTILITY, ["transener"]),
}


def _symbol_candidates(query: str) -> list[str]:
    candidates = re.findall(r"(?<!\w)[A-Z][A-Z0-9._-]{1,29}(?!\w)", query)
    candidates = [value.rstrip("._-") for value in candidates]
    non_asset_terms = {
        "ADR",
        "NYSE",
        "NASDAQ",
        "ARS",
        "USD",
        "ROE",
        "EPS",
        "FCF",
        "RSI",
        "SMA",
        "EMA",
        "MACD",
        "SYSTEM",
        "CALL_TOOL",
        "CALL",
        "TOOL",
    }
    candidates = [value for value in candidates if value not in non_asset_terms]
    # BYMA is a market designator only in explicit market context.
    if "BYMA" in candidates and len(candidates) > 1 and re.search(r"\ben\s+BYMA\b", query, re.I):
        candidates = [value for value in candidates if value != "BYMA"]
    return list(dict.fromkeys(candidates))


def _requested_symbol(query: str) -> str | None:
    candidates = _symbol_candidates(query)
    return next(
        (value for value in candidates if value in CATALOG), candidates[-1] if candidates else None
    )


def resolve_asset(
    query: str,
    *,
    symbol: str | None = None,
    market: str | None = None,
    company_name: str | None = None,
    validator: Callable[[str, str], InstrumentValidation] | None = None,
) -> AssetResolution:
    """Resolve an LLM proposal; only catalog/provider evidence may produce RESOLVED."""
    tokens = set(re.findall(r"[a-z]+", folded(query)))
    foreign_scope = bool(tokens & {"adr", "nyse", "usd", "cedear"})
    symbol = symbol.strip().upper() if symbol else None
    requested_symbol = symbol or _requested_symbol(query)
    explicit_candidates = _symbol_candidates(query)
    if len(explicit_candidates) > 1:
        return AssetResolution(
            status="AMBIGUOUS",
            confidence=0,
            requested_symbol=requested_symbol,
            alternatives=explicit_candidates,
            validation_status="AMBIGUOUS",
        )

    if market and market.casefold() not in {"bcba", "byma"}:
        if requested_symbol and re.fullmatch(TICKER_PATTERN, requested_symbol):
            return AssetResolution(
                status="UNSUPPORTED",
                ticker=requested_symbol,
                market=None,
                confidence=1,
                requested_symbol=requested_symbol,
                alternatives=["El mercado solicitado está fuera del universo BYMA local"],
                validation_status="UNSUPPORTED",
                existence_status="NOT_VERIFIED",
                eligibility_status="UNSUPPORTED",
                eligibility_reason="FOREIGN_MARKET",
                eligibility_method="request_market",
            )
        return AssetResolution(
            status="AMBIGUOUS",
            confidence=0,
            alternatives=["Acción local en BYMA (market=bCBA)"],
            requested_symbol=requested_symbol,
            validation_status="AMBIGUOUS",
        )

    if requested_symbol and not re.fullmatch(TICKER_PATTERN, requested_symbol):
        return AssetResolution(
            status="NOT_FOUND",
            confidence=0,
            requested_symbol=requested_symbol,
            validation_status="INVALID_FORMAT",
        )

    if symbol:
        matches = [symbol]
        exact = [symbol]
    else:
        exact = [t for t in CATALOG if t.lower() in tokens]
        matches = exact or [
            t for t, (_, _, aliases) in CATALOG.items() if any(a in tokens for a in aliases)
        ]

    if len(matches) != 1:
        return AssetResolution(
            status="AMBIGUOUS" if matches else "NOT_FOUND",
            confidence=0,
            alternatives=matches,
            requested_symbol=requested_symbol,
            validation_status="AMBIGUOUS" if matches else "NOT_ATTEMPTED",
        )

    ticker = matches[0]
    if foreign_scope and ticker in CATALOG:
        name, kind, _ = CATALOG[ticker]
        return AssetResolution(
            status="UNSUPPORTED",
            ticker=ticker,
            company_name=name,
            company_type=kind,
            confidence=1,
            requested_symbol=requested_symbol,
            alternatives=["El instrumento o mercado solicitado está fuera del universo BYMA local"],
            validation_status="UNSUPPORTED",
            existence_status="NOT_VERIFIED",
            eligibility_status="UNSUPPORTED",
            eligibility_reason="FOREIGN_MARKET",
            eligibility_method="request_market",
        )
    if ticker not in CATALOG:
        if validator is None:
            return AssetResolution(
                status="NOT_FOUND",
                confidence=0,
                requested_symbol=ticker,
                validation_status="NOT_ATTEMPTED",
            )
        validation = validator(ticker, "bCBA")
        if validation.status == "UNSUPPORTED":
            is_cedear = validation.classification == "CEDEAR"
            return AssetResolution(
                status="UNSUPPORTED",
                ticker=ticker,
                company_name=validation.company_name,
                confidence=1,
                requested_symbol=ticker,
                alternatives=[
                    "El símbolo corresponde a un CEDEAR, fuera del universo de acciones locales"
                    if is_cedear
                    else "El símbolo corresponde a otro tipo de instrumento fuera del universo"
                ],
                validation_method="provider_quote",
                validation_status="UNSUPPORTED",
                validation_source=validation.source,
                existence_status="CONFIRMED",
                eligibility_status="UNSUPPORTED",
                eligibility_reason="CEDEAR" if is_cedear else "OTHER_INSTRUMENT",
                eligibility_method="provider_description_policy",
            )
        if validation.status == "NOT_FOUND":
            return AssetResolution(
                status="NOT_FOUND",
                confidence=0,
                requested_symbol=ticker,
                validation_method="provider_quote",
                validation_status="NOT_FOUND",
                validation_source=validation.source,
                existence_status="NOT_FOUND",
            )
        return AssetResolution(
            status="RESOLVED",
            ticker=ticker,
            company_name=validation.company_name,
            company_type=CompanyType.OTHER,
            market="bCBA",
            confidence=1,
            requested_symbol=ticker,
            validation_method="provider_quote",
            validation_status="VALIDATED",
            validation_source=validation.source,
            existence_status="CONFIRMED",
            eligibility_status="ELIGIBLE",
            eligibility_reason="DOMESTIC_EQUITY",
            eligibility_method="provider_description_policy",
        )

    name, kind, _ = CATALOG[ticker]
    if not exact and ticker == "GGAL":
        return AssetResolution(
            status="AMBIGUOUS",
            confidence=0.6,
            requested_symbol=requested_symbol,
            alternatives=["GGAL (acción BYMA, ARS)", "GGAL (ADR NYSE, USD)"],
            validation_status="AMBIGUOUS",
        )
    return AssetResolution(
        status="RESOLVED",
        ticker=ticker,
        company_name=name,
        company_type=kind,
        market="bCBA",
        confidence=1,
        requested_symbol=requested_symbol,
        validation_method="catalog",
        validation_status="VALIDATED",
        existence_status="CONFIRMED",
        eligibility_status="ELIGIBLE",
        eligibility_reason="DOMESTIC_EQUITY",
        eligibility_method="catalog_metadata",
    )
