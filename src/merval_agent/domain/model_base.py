from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

TICKER_PATTERN = r"^(?:[A-Z]{2,5}|[A-Z]{1,4}[0-9])$"

Ticker = Annotated[
    str,
    StringConstraints(pattern=TICKER_PATTERN),
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
]
HistoryRange = Literal["1W", "1M", "3M", "6M", "1Y"]
CalendarDate = date


def now() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
