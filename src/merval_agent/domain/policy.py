"""Domain policy: six months support SMA50 and intermediate analysis."""

from zoneinfo import ZoneInfo

from .models import HistoryRange

MARKET_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")

DEFAULT_TECHNICAL_RANGE: HistoryRange = "6M"
