"""Replaceable HTML parser: visible columns, never a presumed JSON API."""

import re
import unicodedata
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import TICKER_PATTERN, FinancialDocument


def folded(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value.lower()) if not unicodedata.combining(c)
    )


def parse_documents(html: str) -> list[FinancialDocument]:
    soup = BeautifulSoup(html, "html.parser")
    table = next(
        (
            t
            for t in soup.find_all("table")
            if all(
                label in folded(t.get_text(" ", strip=True))
                for label in ("fecha", "emisor", "especie", "referencia")
            )
        ),
        None,
    )
    if table is None:
        raise ExternalServiceError("Bolsar document table missing; possible HTML change/block")
    documents = []
    for row in table.find_all("tr"):
        cells = [
            c
            for c in row.find_all("td", recursive=False)
            if "display:none" not in c.get("style", "").replace(" ", "")
        ]
        if not cells:
            continue
        if len(cells) != 5:
            raise ExternalServiceError("Unexpected Bolsar row layout")
        link = cells[4].find("a", href=True)
        ticker = cells[2].get_text(strip=True).upper()
        if not link or not re.fullmatch(TICKER_PATTERN, ticker):
            continue  # Issuers without a supported equity symbol are outside the catalog.
        ids = parse_qs(urlparse(link["href"]).query).get("id", [])
        match = re.search(r"\d{2}/\d{2}/\d{4}", cells[0].get_text(" "))
        if not ids or not ids[0].isdigit() or not match:
            raise ExternalServiceError("Invalid Bolsar document id/date")
        reference = cells[3].get_text(" ", strip=True)
        normalized = folded(reference)
        kind = (
            "SUMMARY"
            if "sintesis de estados financieros" in normalized
            else ("FINANCIAL_STATEMENT" if "estados financieros" in normalized else "OTHER")
        )
        documents.append(
            FinancialDocument(
                ticker=ticker,
                issuer=cells[1].get_text(" ", strip=True),
                published_at=datetime.strptime(match[0], "%d/%m/%Y").date(),
                reference=reference,
                document_id=ids[0],
                source_url=f"https://ws.bolsar.info/descarga/?id={ids[0]}",
                document_type=kind,
            )
        )
    return documents


def select_latest(documents: list[FinancialDocument]) -> FinancialDocument | None:
    candidates = [d for d in documents if d.document_type != "OTHER"]
    # Newest publication first; full statements win ties over summaries.
    return max(
        candidates,
        key=lambda d: (
            d.published_at,
            d.document_type == "FINANCIAL_STATEMENT",
            int(d.document_id),
        ),
        default=None,
    )
