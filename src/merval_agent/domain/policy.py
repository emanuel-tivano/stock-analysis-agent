"""Domain policy: six months support SMA50 and intermediate analysis."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from .models import HistoryRange

MARKET_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")
# Argentina Market Tracker has been observed up to 1.112547 seconds ahead of the
# local receiver. Two seconds is the smallest whole-second budget with operating margin.
MAX_PROVIDER_CLOCK_AHEAD = timedelta(seconds=2)

DEFAULT_TECHNICAL_RANGE: HistoryRange = "6M"
