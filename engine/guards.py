from __future__ import annotations

import time

from .config import Config
from .models import Candle, Ticker

TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
    "1d": 86400, "1w": 604800,
}


def candles_stale(candles: list[Candle], cfg: Config, timeframe: str) -> bool:
    if not cfg.check_stale:
        return False
    if not candles:
        return True
    interval = TIMEFRAME_SECONDS.get(timeframe, 3600)
    last_ts = candles[-1].timestamp
    if last_ts > 1_000_000_000_000:
        last_ts /= 1000.0
    if abs(time.time() - last_ts) > interval * cfg.stale_data_multiplier:
        return True
    return False


def validate_ticker(ticker: Ticker, cfg: Config) -> tuple[bool, str]:
    if ticker.last <= 0:
        return False, "bad ticker price"
    spread_pct = 0.0
    if ticker.last > 0:
        spread_pct = (ticker.ask - ticker.bid) / ticker.last * 100.0
    if spread_pct > cfg.max_spread_pct:
        return False, f"spread {spread_pct:.2f}% above {cfg.max_spread_pct:.2f}%"
    if cfg.min_volume_24h > 0 and ticker.volume_24h < cfg.min_volume_24h:
        return False, f"24h volume {ticker.volume_24h:.0f} below {cfg.min_volume_24h:.0f}"
    return True, "ok"