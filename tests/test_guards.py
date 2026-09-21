import tempfile
import time
import unittest
from pathlib import Path

from engine.config import Config
from engine.guards import candles_stale, validate_ticker
from engine.models import Candle, Ticker


def make_cfg(**overrides):
    cfg = Config()
    cfg.data_dir = Path(tempfile.mkdtemp(prefix="atlas-guard-"))
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def fresh_candle(ts: int | None = None) -> Candle:
    return Candle(timestamp=ts or int(time.time()), open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


class TestCandlesStale(unittest.TestCase):
    def test_fresh_candles_not_stale(self):
        cfg = make_cfg(stale_data_multiplier=3)
        candles = [fresh_candle(), fresh_candle(), fresh_candle()]
        self.assertFalse(candles_stale(candles, cfg, "1h"))

    def test_fresh_ms_candles_not_stale(self):
        cfg = make_cfg(stale_data_multiplier=3)
        ms = lambda s: int((time.time() + s) * 1000)
        candles = [Candle(ms(0), 1, 1, 1, 1, 1)]
        self.assertFalse(candles_stale(candles, cfg, "1h"))

    def test_old_ms_candles_stale(self):
        cfg = make_cfg(stale_data_multiplier=3)
        old_ms = int((time.time() - 3600 * 4) * 1000)
        candles = [Candle(old_ms, 1, 1, 1, 1, 1)]
        self.assertTrue(candles_stale(candles, cfg, "1h"))

    def test_old_candles_stale(self):
        cfg = make_cfg(stale_data_multiplier=3)
        old = int(time.time()) - 3600 * 4
        candles = [Candle(old, 1, 1, 1, 1, 1)]
        self.assertTrue(candles_stale(candles, cfg, "1h"))

    def test_empty_always_stale(self):
        cfg = make_cfg()
        self.assertTrue(candles_stale([], cfg, "1h"))

    def test_disabled_never_stale(self):
        cfg = make_cfg(check_stale=False)
        candles = [Candle(int(time.time()) - 86400 * 300, 1, 1, 1, 1, 1)]
        self.assertFalse(candles_stale(candles, cfg, "1h"))


class TestValidateTicker(unittest.TestCase):
    def test_healthy_ticker(self):
        cfg = make_cfg(max_spread_pct=1.0, min_volume_24h=0.0)
        ok, reason = validate_ticker(Ticker("BTC/USDT", last=100, bid=99.99, ask=100.01), cfg)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_wide_spread_rejected(self):
        cfg = make_cfg(max_spread_pct=1.0)
        ticker = Ticker("SOL/USDT", last=100, bid=90, ask=110)
        ok, reason = validate_ticker(ticker, cfg)
        self.assertFalse(ok)
        self.assertIn("spread", reason)

    def test_low_volume_rejected(self):
        cfg = make_cfg(min_volume_24h=500_000.0)
        ticker = Ticker("DOGE/USDT", last=0.1, bid=0.1, ask=0.1, volume_24h=100.0)
        ok, reason = validate_ticker(ticker, cfg)
        self.assertFalse(ok)
        self.assertIn("volume", reason)

    def test_zero_price_rejected(self):
        cfg = make_cfg()
        ok, _ = validate_ticker(Ticker("X/USDT", last=0, bid=0, ask=0), cfg)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()