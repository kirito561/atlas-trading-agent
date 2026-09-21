from __future__ import annotations

from ..config import Config
from ..models import Analysis


def apply_sentiment(analysis: Analysis, sentiment: dict) -> Analysis:
    score = analysis.score
    if sentiment and sentiment.get("label") != "neutral":
        adjustment = sentiment["score"] * max(0.2, sentiment.get("confidence", 0.0))
        if sentiment["label"] == "bullish":
            score += adjustment
        else:
            score -= adjustment
        analysis.factors["sentiment"] = sentiment["label"]
        analysis.factors["sentiment_score"] = round(score, 3)
    return analysis


def finalize_conviction(analysis: Analysis, cfg: Config) -> Analysis:
    score = analysis.score
    s = abs(score)
    if s >= 3.0:
        cv = 10
    elif s >= 2.3:
        cv = 9
    elif s >= 1.8:
        cv = 8
    elif s >= 1.2:
        cv = 7
    elif s >= 0.8:
        cv = 6
    elif s >= 0.5:
        cv = 5
    else:
        cv = 3
    analysis.conviction = cv
    analysis.score = round(score, 3)
    return analysis


def should_enter(analysis: Analysis, cfg: Config) -> tuple[bool, str]:
    if analysis.direction == "neutral":
        return False, "neutral signal"
    if analysis.conviction < cfg.min_conviction:
        return False, f"conviction {analysis.conviction} below minimum {cfg.min_conviction}"
    if analysis.direction == "short" and not cfg.allow_short:
        return False, "shorting disabled"
    return True, "ok"