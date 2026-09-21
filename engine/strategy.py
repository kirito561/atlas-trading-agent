from __future__ import annotations

from .analysis.scoring import apply_sentiment, finalize_conviction, should_enter
from .analysis.sentiment import SentimentAnalyzer
from .analysis.technical import analyze_candles
from .broker.base import Broker
from .config import Config
from .guards import candles_stale
from .models import Analysis


def score_symbol(broker: Broker, sentiment: SentimentAnalyzer | None,
                 symbol: str, cfg: Config, timeframe: str, limit: int = 300) -> tuple[Analysis | None, str | None]:
    try:
        candles = broker.fetch_candles(symbol, timeframe, limit)
    except Exception as e:
        return None, f"data fetch failed: {e}"
    if candles_stale(candles, cfg, timeframe):
        return None, "stale data"
    analysis = analyze_candles(symbol, candles)
    if analysis is None:
        return None, "insufficient data"
    if sentiment is not None:
        analysis = apply_sentiment(analysis, sentiment.analyze(symbol))
    analysis = finalize_conviction(analysis, cfg)
    return analysis, None


def decide_entry(analysis: Analysis, cfg: Config) -> tuple[bool, str]:
    return should_enter(analysis, cfg)