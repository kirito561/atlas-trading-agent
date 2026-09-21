from __future__ import annotations

import numpy as np


def _as_array(values: list[float] | np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=float)


def sma(values: list[float] | np.ndarray, period: int) -> np.ndarray:
    v = _as_array(values)
    n = v.size
    out = np.full(n, np.nan)
    if n < period or period <= 0:
        return out
    c = np.cumsum(v)
    out[period - 1:] = c[period - 1:] / period
    if period > 1:
        out[period:] = (c[period:] - c[:-period]) / period
        out[:period - 1] = np.nan
    return out


def ema(values: list[float] | np.ndarray, period: int) -> np.ndarray:
    v = _as_array(values)
    n = v.size
    out = np.full(n, np.nan)
    if n < period or period <= 0:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = float(np.mean(v[:period]))
    out[period - 1] = seed
    for i in range(period, n):
        out[i] = alpha * v[i] + (1.0 - alpha) * out[i - 1]
    return out


def rsi(values: list[float] | np.ndarray, period: int = 14) -> np.ndarray:
    v = _as_array(values)
    n = v.size
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    delta = np.diff(v)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss) if avg_loss != 0 else 100.0
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss) if avg_loss != 0 else 100.0
    return out


def macd(values: list[float] | np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    v = _as_array(values)
    n = v.size
    line = ema(v, fast) - ema(v, slow)
    sig = np.full(n, np.nan)
    first = int(np.argmax(~np.isnan(line)))
    seg = line[first:]
    if seg.size >= signal:
        sig_seg = ema(seg, signal)
        sig[first:] = sig_seg
    hist = np.where(np.isnan(sig), np.nan, line - sig)
    return line, sig, hist


def bollinger(values: list[float] | np.ndarray, period: int = 20, num_std: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    v = _as_array(values)
    n = v.size
    upper = np.full(n, np.nan)
    mid = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    if n < period:
        return upper, mid, lower
    mid = sma(v, period)
    c = np.cumsum(v * v)
    running = np.full(n, np.nan)
    running[period - 1:] = c[period - 1:] / period
    if period > 1:
        running[period:] = (c[period:] - c[:-period]) / period
    var = running - mid * mid
    var = np.maximum(var, 0.0)
    sd = np.sqrt(var)
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    return upper, mid, lower


def atr(candles: list, period: int = 14) -> np.ndarray:
    n = len(candles)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    closes = np.array([c.close for c in candles], dtype=float)
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0]
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
    out[period] = float(np.mean(tr[1:period + 1]))
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def vwap(candles: list) -> np.ndarray:
    n = len(candles)
    if n == 0:
        return np.array([])
    tp = np.array([(c.high + c.low + c.close) / 3.0 for c in candles], dtype=float)
    vol = np.array([c.volume for c in candles], dtype=float)
    cum_tp = np.cumsum(tp * vol)
    cum_vol = np.cumsum(vol)
    cum_vol = np.where(cum_vol == 0, np.nan, cum_vol)
    return cum_tp / cum_vol


def _rolling_minmax(values: np.ndarray, period: int) -> tuple[np.ndarray, np.ndarray]:
    n = values.size
    rmin = np.full(n, np.nan)
    rmax = np.full(n, np.nan)
    if n < period:
        return rmin, rmax
    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(values, period)
    rmin[period - 1:] = windows.min(axis=1)
    rmax[period - 1:] = windows.max(axis=1)
    return rmin, rmax


def stoch(candles: list, k_period: int = 14, d_period: int = 3) -> tuple[np.ndarray, np.ndarray]:
    n = len(candles)
    k_out = np.full(n, np.nan)
    d_out = np.full(n, np.nan)
    if n < k_period + d_period:
        return k_out, d_out
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    closes = np.array([c.close for c in candles], dtype=float)
    rmin, rmax = _rolling_minmax(lows, k_period), _rolling_minmax(highs, k_period)
    rng = rmax[1] - rmin[0]
    rng = np.where(rmax - rmin == 0, np.nan, rmax - rmin)
    raw_k = (closes - rmin) / rng * 100.0
    k_out = sma(raw_k, d_period)
    d_out = sma(np.where(np.isnan(k_out), np.nan, k_out), 3)
    return k_out, d_out


def adx(candles: list, period: int = 14) -> np.ndarray:
    n = len(candles)
    out = np.full(n, np.nan)
    if n < period * 2:
        return out
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    closes = np.array([c.close for c in candles], dtype=float)
    up_move = np.zeros(n)
    down_move = np.zeros(n)
    up_move[1:] = np.diff(highs)
    down_move[1:] = -np.diff(lows)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0]
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))

    def smooth(raw: np.ndarray, p: int) -> np.ndarray:
        res = np.full(n, np.nan)
        res[p] = float(np.mean(raw[1:p + 1]))
        for i in range(p + 1, n):
            res[i] = (res[i - 1] * (p - 1) + raw[i]) / p
        return res

    s_tr = smooth(tr, period)
    s_pdm = smooth(plus_dm, period)
    s_mdm = smooth(minus_dm, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * np.where(s_tr == 0, np.nan, s_pdm / s_tr)
        minus_di = 100.0 * np.where(s_tr == 0, np.nan, s_mdm / s_tr)
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    start = period
    seg = dx[start:]
    if seg.size >= period * 2:
        first_idx = start + period
        out[first_idx] = float(np.mean(seg[:period]))
        for i in range(first_idx + 1, n):
            out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out


def roc(values: list[float] | np.ndarray, period: int = 1) -> np.ndarray:
    v = _as_array(values)
    n = v.size
    out = np.full(n, np.nan)
    if n <= period:
        return out
    out[period:] = (v[period:] - v[:-period]) / np.where(v[:-period] == 0, np.nan, v[:-period])
    return out