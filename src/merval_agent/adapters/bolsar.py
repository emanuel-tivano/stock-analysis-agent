import httpx
from pydantic import TypeAdapter

from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import FinancialDocument, Ticker

from .bolsar_parser import parse_documents, select_latest


class BolsarClient:
    def __init__(self, http: httpx.Client, base_url: str = "https://bolsar.info"):
        self.http = http
        self.base_url = base_url.rstrip("/")

    def list_documents(
        self, ticker: str, year: int | None = None, semester: int | None = None
    ) -> list[FinancialDocument]:
        ticker = TypeAdapter(Ticker).validate_python(ticker)
        if semester not in (None, 1, 2):
            raise ValueError("semester must be 1 or 2")
        if year is not None and not 1900 <= year <= 2200:
            raise ValueError("invalid year")
        try:
            response = self.http.get(f"{self.base_url}/relevante_semestral.php")
            response.raise_for_status()
            docs = parse_documents(response.text)
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("Bolsar unavailable or malformed document rows") from exc
        # Publication filters on the exposed page, not a claim of archive/fiscal coverage.
        return sorted(
            [
                d
                for d in docs
                if d.ticker == ticker
                and (year is None or d.published_at.year == year)
                and (semester is None or (d.published_at.month - 1) // 6 + 1 == semester)
            ],
            key=lambda d: d.published_at,
            reverse=True,
        )

    def find_latest_financial_statement(self, ticker: str) -> FinancialDocument | None:
        return select_latest(self.list_documents(ticker))
