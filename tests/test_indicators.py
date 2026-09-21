import math
import unittest

import numpy as np

from engine.indicators import adx, atr, bollinger, ema, macd, rsi, sma, vwap
from engine.models import Candle


def candles_from_closes(closes, seed=7.0, vol=10.0):
    out = []
    prev = seed
    for c in closes:
        lo = min(prev, c) * 0.995
        hi = max(prev, c) * 1.005
        out.append(Candle(0, prev, hi, lo, c, vol))
        prev = c
    return out


class TestSma(unittest.TestCase):
    def test_basic(self):
        v = [1, 2, 3, 4, 5]
        result = sma(v, 3)
        self.assertTrue(math.isnan(result[0]))
        self.assertTrue(math.isnan(result[1]))
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)
        self.assertAlmostEqual(result[4], 4.0)

    def test_short_series(self):
        result = sma([1, 2], 3)
        self.assertTrue(all(math.isnan(x) for x in result))


class TestEma(unittest.TestCase):
    def test_reaches_value_and_warms_up(self):
        v = [10.0] * 40
        result = ema(v, 10)
        self.assertTrue(math.isnan(result[8]))
        self.assertTrue(result[9] == result[-1] == 10.0)

    def test_increasing(self):
        v = list(range(1, 40))
        result = ema(v, 5)
        valid = result[~np.isnan(result)]
        self.assertTrue(np.all(np.diff(valid) > 0))


class TestRsi(unittest.TestCase):
    def test_all_gain_gives_100(self):
        v = [1.0 + i * 0.1 for i in range(30)]
        result = rsi(v, 14)
        self.assertAlmostEqual(result[-1], 100.0, delta=0.001)

    def test_all_loss_gives_0(self):
        v = [30.0 - i * 0.1 for i in range(30)]
        result = rsi(v, 14)
        self.assertAlmostEqual(result[-1], 0.0, delta=0.01)

    def test_bounds(self):
        v = [10 + math.sin(i / 3) * 3 for i in range(100)]
        result = rsi(v, 14)
        valid = result[~np.isnan(result)]
        self.assertTrue(np.all((valid >= 0) & (valid <= 100)))


class TestMacd(unittest.TestCase):
    def test_shape_and_existence(self):
        v = [10 + i * 0.02 for i in range(120)]
        line, sig, hist = macd(v)
        self.assertEqual(len(line), 120)
        valid = hist[~np.isnan(hist)]
        self.assertGreater(len(valid), 50)
        self.assertTrue(math.isnan(hist[0]))

    def test_uptrend_positive_hist(self):
        v = [10.0 * (1.02 ** i) for i in range(160)]
        line, sig, hist = macd(v)
        self.assertGreater(hist[-1], 0)


class TestBollinger(unittest.TestCase):
    def test_upper_above_lower(self):
        v = [100 + math.sin(i / 5) * 2 for i in range(60)]
        upper, mid, lower = bollinger(v)
        self.assertGreater(upper[-1], mid[-1])
        self.assertGreater(mid[-1], lower[-1])
        self.assertAlmostEqual(mid[-1], np.mean(v[-20:]), delta=0.01)


class TestAtr(unittest.TestCase):
    def test_converges_today(self):
        candles = candles_from_closes([100.0 + i for i in range(30)], seed=100.0)
        result = atr(candles, 14)
        valid = result[~np.isnan(result)]
        self.assertGreater(len(valid), 3)


class TestVwap(unittest.TestCase):
    def test_matches_formula(self):
        candles = [Candle(0, i, i + 1, i - 1, i, 10.0) for i in range(1, 50)]
        result = vwap(candles)
        last = result[-1]
        tp = [((c.high + c.low + c.close) / 3.0) for c in candles]
        expected = sum(t * 10 for t, c in zip(tp, candles)) / sum(10 for _ in candles)
        self.assertAlmostEqual(last, expected, delta=0.01)


class TestAdx(unittest.TestCase):
    def test_trending_series_has_values(self):
        closes = [100 + i * 0.4 for i in range(60)]
        candles = candles_from_closes(closes, seed=100.0)
        result = adx(candles, 14)
        valid = result[~np.isnan(result)]
        self.assertGreater(len(valid), 3)
        self.assertGreater(np.mean(valid), 0)


if __name__ == "__main__":
    unittest.main()