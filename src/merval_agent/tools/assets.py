import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from merval_agent.adapters.market_tracker import InstrumentValidation
from merval_agent.domain.models import TICKER_PATTERN, AssetResolution, CompanyType


def folded(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value.lower()) if not unicodedata.combining(c)
    )


@dataclass(frozen=True)
class CatalogAsset:
    name: str
    company_type: CompanyType
    aliases: tuple[str, ...]
    alias_alternatives: tuple[str, ...] = ()


CATALOG = {
    "GGAL": CatalogAsset(
        "Grupo Financiero Galicia",
        CompanyType.FINANCIAL,
        ("galicia",),
        ("GGAL (acción BYMA, ARS)", "GGAL (ADR NYSE, USD)"),
    ),
    "BMA": CatalogAsset("Banco Macro", CompanyType.FINANCIAL, ("macro",)),
    "SUPV": CatalogAsset("Grupo Supervielle", CompanyType.FINANCIAL, ("supervielle",)),
    "PAMP": CatalogAsset("Pampa Energía", CompanyType.ENERGY, ("pampa",)),
    "YPFD": CatalogAsset("YPF", CompanyType.ENERGY, ("ypf",)),
    "ALUA": CatalogAsset("Aluar", CompanyType.INDUSTRIAL, ("aluar",)),
    "TRAN": CatalogAsset("Transener", CompanyType.UTILITY, ("transener",)),
}


def symbol_candidates(query: str) -> list[str]:
    candidates = re.findall(r"(?<!\w)[A-Z][A-Z0-9._-]{1,29}(?!\w)", query)
    candidates = [value.rstrip("._-") for value in candidates]
    non_asset_terms = {
        "ADR",
        "CEDEAR",
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
    candidates = symbol_candidates(query)
    return next(
        (value for value in candidates if value in CATALOG), candidates[-1] if candidates else None
    )


def explicit_user_symbol(query: str) -> str | None:
    """Return one ticker written by the user, never an inferred alias."""
    candidates = symbol_candidates(query)
    if len(candidates) == 1:
        return candidates[0]
    tokens = set(re.findall(r"[a-z]+", folded(query)))
    exact = [ticker for ticker in CATALOG if ticker.casefold() in tokens]
    return exact[0] if len(exact) == 1 else None


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
    explicit_candidates = symbol_candidates(query)
    requested_symbol = explicit_user_symbol(query) or symbol or _requested_symbol(query)
    if len(explicit_candidates) > 1:
        return AssetResolution(
            status="AMBIGUOUS",
            confidence=0,
            requested_symbol=requested_symbol,
            alternatives=explicit_candidates,
            validation_status="AMBIGUOUS",
        )

    exact = [ticker for ticker in CATALOG if ticker.casefold() in tokens]
    aliases = [
        ticker
        for ticker, entry in CATALOG.items()
        if any(alias in tokens for alias in entry.aliases)
    ]
    local_matches = exact or aliases
    if len(local_matches) > 1:
        return AssetResolution(
            status="AMBIGUOUS",
            confidence=0,
            alternatives=local_matches,
            requested_symbol=requested_symbol,
            validation_status="AMBIGUOUS",
        )
    if len(local_matches) == 1 and not exact:
        alternatives = CATALOG[local_matches[0]].alias_alternatives
        if alternatives:
            return AssetResolution(
                status="AMBIGUOUS",
                confidence=0.6,
                requested_symbol=requested_symbol,
                alternatives=list(alternatives),
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

    matches = local_matches or ([symbol] if symbol else [])

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
        entry = CATALOG[ticker]
        return AssetResolution(
            status="UNSUPPORTED",
            ticker=ticker,
            company_name=entry.name,
            company_type=entry.company_type,
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

    entry = CATALOG[ticker]
    return AssetResolution(
        status="RESOLVED",
        ticker=ticker,
        company_name=entry.name,
        company_type=entry.company_type,
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
