import re

from merval_agent.adapters.bolsar_parser import folded
from merval_agent.domain.models import AssetResolution, CompanyType

CATALOG = {
    "GGAL": ("Grupo Financiero Galicia", CompanyType.FINANCIAL, ["galicia"]),
    "BMA": ("Banco Macro", CompanyType.FINANCIAL, ["macro"]),
    "SUPV": ("Grupo Supervielle", CompanyType.FINANCIAL, ["supervielle"]),
    "PAMP": ("Pampa Energía", CompanyType.ENERGY, ["pampa"]),
    "YPFD": ("YPF", CompanyType.ENERGY, ["ypf"]),
    "ALUA": ("Aluar", CompanyType.INDUSTRIAL, ["aluar"]),
    "TRAN": ("Transener", CompanyType.UTILITY, ["transener"]),
}


def resolve_asset(query: str) -> AssetResolution:
    tokens = set(re.findall(r"[a-z]+", folded(query)))
    if tokens & {"adr", "nyse", "usd", "cedear"}:
        return AssetResolution(
            confidence=0,
            alternatives=[
                "Confirmar acción local BYMA en ARS; otros instrumentos fuera de cobertura"
            ],
        )
    exact = [t for t in CATALOG if t.lower() in tokens]
    matches = exact or [
        t for t, (_, _, aliases) in CATALOG.items() if any(a in tokens for a in aliases)
    ]
    if len(matches) != 1:
        return AssetResolution(confidence=0, alternatives=matches)
    ticker = matches[0]
    name, kind, _ = CATALOG[ticker]
    if not exact and ticker == "GGAL":
        return AssetResolution(
            confidence=0.6, alternatives=["GGAL (acción BYMA, ARS)", "GGAL (ADR NYSE, USD)"]
        )
    return AssetResolution(ticker=ticker, company_name=name, company_type=kind, confidence=1)
