from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BULLISH = {
    "soar", "surge", "spike", "rally", "gain", "bull", "bullish", "beat", "upgrade",
    "breakout", "approve", "adoption", "partnership", "growth", "record", "all-time high",
    "mainnet", "launch", "inflow", "whale buys", "accumulat",
}
BEARISH = {
    "crash", "plunge", "tumble", "slump", "sell-off", "selloff", "bear", "bearish",
    "miss", "downgrade", "ban", "lawsuit", "fraud", "hack", "exploit", "outflow",
    "recession", "inflation", "fear", "dump", "bankruptcy", "investigation", "delist",
    "outflow", "whale sells", "liquidation",
}


class SentimentAnalyzer:
    def __init__(self, enabled: bool = False, cache_seconds: int = 1800) -> None:
        self.enabled = enabled
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, dict]] = {}

    def analyze(self, symbol: str) -> dict:
        now = time.time()
        cached = self._cache.get(symbol)
        if cached and now - cached[0] < self.cache_seconds:
            return cached[1]

        if not self.enabled:
            result = {"label": "neutral", "score": 0.0, "confidence": 0.0, "headlines": 0}
            self._cache[symbol] = (now, result)
            return result

        result = self._fetch(symbol)
        self._cache[symbol] = (now, result)
        return result

    def _fetch(self, symbol: str) -> dict:
        coin = symbol.split("/")[0]
        queries = [f"{coin} crypto", f"{coin} price"]
        scored = []
        for query in queries:
            try:
                url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query, safe="") + "&hl=en-US&gl=US&ceid=US:en"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    body = resp.read()
                root = ET.fromstring(body)
                for item in root.iter("item"):
                    title = (item.findtext("title") or "").lower()
                    if not title:
                        continue
                    bull = sum(1 for w in BULLISH if w in title)
                    bear = sum(1 for w in BEARISH if w in title)
                    if bull or bear:
                        scored.append((bull - bear) / max(1, bull + bear))
            except Exception:
                continue
        if not scored:
            result = {"label": "neutral", "score": 0.0, "confidence": 0.0, "headlines": 0}
        else:
            avg = sum(scored) / len(scored)
            label = "bullish" if avg > 0.05 else "bearish" if avg < -0.05 else "neutral"
            result = {"label": label, "score": avg, "confidence": min(1.0, len(scored) / 5.0), "headlines": len(scored)}
        return result


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")