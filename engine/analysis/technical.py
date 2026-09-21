from __future__ import annotations

import numpy as np

from .. import indicators as ta
from ..models import Analysis, Candle


def analyze_candles(symbol: str, candles: list[Candle]) -> Analysis | None:
    n = len(candles)
    if n < 120:
        return None
    closes = np.array([c.close for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    volumes = np.array([c.volume for c in candles], dtype=float)
    price = float(closes[-1])

    ema20 = ta.ema(closes, 20)
    ema50 = ta.ema(closes, 50)
    ema200 = ta.ema(closes, 200)
    rsi = ta.rsi(closes, 14)
    macd_line, macd_sig, macd_hist = ta.macd(closes)
    bb_upper, bb_mid, bb_lower = ta.bollinger(closes, 20, 2.0)
    atr_arr = ta.atr(candles, 14)
    vwap_arr = ta.vwap(candles)
    adx_arr = ta.adx(candles, 14)
    ema20_slope = ema20[-1] - ema20[-2] if not np.isnan(ema20[-1]) and not np.isnan(ema20[-2]) else np.nan

    signals: list[dict] = []

    def add(name: str, side: str, weight: float, detail: str = "") -> None:
        signals.append({"name": name, "side": side, "weight": weight, "detail": detail})

    trend = "neutral"
    if not (np.isnan(ema50[-1]) or np.isnan(ema200[-1]) or np.isnan(ema20[-1])):
        if price > ema50[-1] > ema200[-1] and ema20_slope > 0:
            trend = "long"
            add("trend", "long", 1.5, "price>ema50>ema200, ema20 rising")
        elif price < ema50[-1] < ema200[-1] and ema20_slope < 0:
            trend = "short"
            add("trend", "short", 1.5, "price<ema50<ema200, ema20 falling")
        elif price > ema50[-1]:
            trend = "long"
            add("trend", "long", 0.6, "price above ema50")
        else:
            trend = "short"
            add("trend", "short", 0.6, "price below ema50")

    if not np.isnan(macd_hist[-1]) and not np.isnan(macd_hist[-2]):
        rising = macd_hist[-1] > macd_hist[-2]
        if macd_hist[-1] > 0 and rising:
            add("macd", "long", 1.0, "hist positive and rising")
        elif macd_hist[-1] < 0 and not rising:
            add("macd", "short", 1.0, "hist negative and falling")
        elif macd_hist[-1] > 0:
            add("macd", "short", 0.3, "hist positive but fading")
        else:
            add("macd", "long", 0.3, "hist negative but recovering")

    if not np.isnan(rsi[-1]):
        if rsi[-1] < 35:
            add("rsi", "long", 0.5 if trend == "long" else 0.2, f"rsi {rsi[-1]:.1f} oversold")
        elif rsi[-1] < 45 and trend == "long":
            add("rsi", "long", 0.4, f"rsi {rsi[-1]:.1f} retrace above 30")
        elif rsi[-1] > 65:
            add("rsi", "short", 0.5 if trend == "short" else 0.2, f"rsi {rsi[-1]:.1f} overbought")
        elif rsi[-1] > 55 and trend == "short":
            add("rsi", "short", 0.4, f"rsi {rsi[-1]:.1f} bounce below 70")

    if not (np.isnan(bb_lower[-1]) or np.isnan(bb_upper[-1])):
        if price < bb_lower[-1]:
            add("bollinger", "long", 0.4, "below lower band")
        elif price > bb_upper[-1]:
            add("bollinger", "short", 0.4, "above upper band")

    lookback = 20
    recent_high = float(np.max(highs[-lookback - 1:-1]))
    recent_low = float(np.min(lows[-lookback - 1:-1]))
    if price > recent_high:
        add("breakout", "long", 1.2, f"close above {lookback}-bar high")
    elif price < recent_low:
        add("breakout", "short", 1.2, f"close below {lookback}-bar low")

    vol_avg = float(np.mean(volumes[-21:-1])) if n >= 22 else 0.0
    if vol_avg > 0 and volumes[-1] > 1.5 * vol_avg:
        add("volume", trend if trend != "neutral" else "long", 0.4, "volume spike")

    if not np.isnan(vwap_arr[-1]):
        if price > vwap_arr[-1]:
            add("vwap", "long", 0.4, "above vwap")
        else:
            add("vwap", "short", 0.4, "below vwap")

    if not np.isnan(adx_arr[-1]):
        if adx_arr[-1] > 25 and trend != "neutral":
            add("adx", trend, 0.5, f"adx {adx_arr[-1]:.1f} trend strength")

    bull = sum(s["weight"] for s in signals if s["side"] == "long")
    bear = sum(s["weight"] for s in signals if s["side"] == "short")
    score = bull - bear

    direction = "neutral"
    if score >= 0.5:
        direction = "long"
    elif score <= -0.5:
        direction = "short"

    atr_value = float(atr_arr[-1]) if not np.isnan(atr_arr[-1]) and atr_arr[-1] > 0 else price * 0.02
    atr_pct = atr_value / price if price else 0.02
    stop_pct = min(0.10, max(0.012, atr_pct * 1.5))

    factors = {
        "trend": trend,
        "rsi": float(rsi[-1]) if not np.isnan(rsi[-1]) else None,
        "macd_hist": float(macd_hist[-1]) if not np.isnan(macd_hist[-1]) else None,
        "adx": float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else None,
        "atr_pct": atr_pct,
        "vol_ratio": float(volumes[-1] / vol_avg) if vol_avg else None,
        "bull": bull,
        "bear": bear,
    }
    return Analysis(
        symbol=symbol,
        direction=direction,
        score=score,
        conviction=_conviction(score),
        price=price,
        atr_pct=atr_pct,
        stop_pct=stop_pct,
        signals=signals,
        factors=factors,
    )


def _conviction(score: float) -> int:
    s = abs(score)
    if s >= 3.0:
        return 10
    if s >= 2.3:
        return 9
    if s >= 1.8:
        return 8
    if s >= 1.2:
        return 7
    if s >= 0.8:
        return 6
    if s >= 0.5:
        return 5
    return 3