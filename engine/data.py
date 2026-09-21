from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import numpy as np

from .models import Candle, Ticker

BYBIT_BASE = "https://api.bybit.com"
_BASE_ENDPOINTS = ["https://api.bybit.com", "https://api.bytick.com"]

TIMEFRAME_MAP = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
    "1d": "D", "1w": "W",
}


class BybitData:
    def __init__(self, cfg=None, category: str = "spot", retries: int = 2, backoff: float = 0.6) -> None:
        self.category = category
        self.retries = retries
        self.backoff = backoff
        self._cache_ts = 0.0
        self._ticker_cache: dict[str, tuple[float, Ticker]] = {}

    def _request(self, path: str, params: dict) -> dict:
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            for base in _BASE_ENDPOINTS:
                url = base + path + "?" + urllib.parse.urlencode(params)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "ATLAS/1.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    if body.get("retCode") == 0:
                        return body.get("result") or {}
                    last_err = RuntimeError(body.get("retMsg", "unknown bybit error"))
                except Exception as e:
                    last_err = e
            if attempt < self.retries:
                time.sleep(self.backoff * (attempt + 1))
        raise RuntimeError(f"bybit request failed: {last_err}")

    def _symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").upper()

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        interval = TIMEFRAME_MAP.get(timeframe)
        if interval is None:
            raise ValueError(f"unsupported timeframe {timeframe}")
        result = self._request("/v5/market/kline", {
            "category": self.category,
            "symbol": self._symbol(symbol),
            "interval": interval,
            "limit": limit,
        })
        rows = result.get("list", [])
        candles = []
        for row in rows:
            candles.append(Candle(
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            ))
        candles.reverse()
        return candles

    def fetch_ticker(self, symbol: str) -> Ticker:
        row = self._request("/v5/market/tickers", {
            "category": self.category,
            "symbol": self._symbol(symbol),
        })
        items = row.get("list", [])
        if not items:
            raise RuntimeError(f"no ticker for {symbol}")
        t = items[0]
        bid = float(t.get("bid1Price") or t.get("bid1") or 0)
        ask = float(t.get("ask1Price") or t.get("ask1") or 0)
        last = float(t.get("lastPrice") or 0)
        if last == 0:
            last = (bid + ask) / 2 if (bid + ask) else 0
        return Ticker(
            symbol=symbol,
            last=last,
            bid=bid or last,
            ask=ask or last,
            change_pct=float(t.get("price24hPcnt") or 0),
            volume_24h=float(t.get("turnover24h") or 0),
            timestamp=int(t.get("timestamp") or time.time() * 1000),
        )


class SynthData:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = np.random.default_rng(seed)

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        start_price = 100.0 + (hash(symbol) % 300)
        n = max(limit, 400)
        drift = 0.0002
        vol = 0.02
        prices = [start_price]
        for i in range(n):
            regime = 1 if i % 120 < 80 else -0.5
            shock = 0.06 if i % 200 == 0 else 0.0
            ret = drift + vol * regime * self.rng.normal(0, 1) * 0.3 + shock * (1 if self.rng.random() < 0.5 else -1)
            prices.append(prices[-1] * (1 + ret))
        interval = 3600
        base = int(time.time()) - n * interval
        candles = []
        for i in range(n):
            o = prices[i]
            c = prices[i + 1]
            hi = max(o, c) * (1 + abs(self.rng.normal(0, 0.004)))
            lo = min(o, c) * (1 - abs(self.rng.normal(0, 0.004)))
            v = 1000.0 * self.rng.random() * (1 + 3 * abs(self.rng.normal()))
            candles.append(Candle(timestamp=base + i * interval, open=o, high=hi, low=lo, close=c, volume=v))
        return candles

    def fetch_ticker(self, symbol: str) -> Ticker:
        candles = self.fetch_candles(symbol, "1m", 2)
        last = candles[-1].close
        return Ticker(symbol=symbol, last=last, bid=last, ask=last)