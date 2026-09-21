import tempfile
import time
import unittest
from pathlib import Path

from engine.broker.paper import PaperBroker
from engine.config import Config
from engine.lock import InstanceLock
from engine.models import Side, Ticker


class FlatFetcher:
    def fetch_candles(self, symbol, timeframe, limit=300):
        return []

    def fetch_ticker(self, symbol):
        return Ticker(symbol=symbol, last=100.0, bid=100.0, ask=100.0)


def make_cfg(**overrides):
    cfg = Config()
    cfg.data_dir = Path(tempfile.mkdtemp(prefix="atlas-test-"))
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class TestFunding(unittest.TestCase):
    def test_funding_charged_on_close(self):
        cfg = make_cfg(funding_rate=0.0001)
        broker = PaperBroker(cfg, fetcher=None)
        broker.open_position("BTC/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        position = broker.get_positions()[0]
        position.opened_at = int(time.time()) - 8 * 3600
        trade = broker.close_position(position, 100.0, "take_profit")
        hours = (time.time() - position.opened_at) / 3600.0
        funding = position.qty * position.entry * cfg.funding_rate * (hours / 8.0)
        expected = -0.10 - position.qty * position.entry * cfg.fee_rate * 2 - funding
        self.assertAlmostEqual(trade.pnl, expected, places=6)
        self.assertGreater(funding, 0.009)


class TestReconcile(unittest.TestCase):
    def test_paper_adopts_positions_from_disk(self):
        cfg = make_cfg()
        broker1 = PaperBroker(cfg, fetcher=FlatFetcher())
        broker1.open_position("BTC/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        broker2 = PaperBroker(cfg, fetcher=FlatFetcher())
        self.assertEqual(len(broker2.get_positions()), 1)
        broker2.open_position("ETH/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        result = broker1.reconcile()
        self.assertIn("ETH/USDT", result["adopted"])
        self.assertEqual(len(broker1.get_positions()), 2)


class TestFlatten(unittest.TestCase):
    def test_flatten_closes_all(self):
        cfg = make_cfg()
        broker = PaperBroker(cfg, fetcher=FlatFetcher())
        broker.open_position("BTC/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        broker.open_position("ETH/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        closed = broker.flatten()
        self.assertEqual(len(closed), 2)
        self.assertEqual(broker.get_positions(), [])


class TestInstanceLock(unittest.TestCase):
    def test_second_instance_denied(self):
        cfg = make_cfg()
        lock1 = InstanceLock(cfg.lock_file)
        lock2 = InstanceLock(cfg.lock_file)
        self.assertTrue(lock1.acquire(hold=True))
        self.assertFalse(lock2.acquire(hold=True))
        lock1.release()
        lock3 = InstanceLock(cfg.lock_file)
        self.assertTrue(lock3.acquire(hold=True))
        lock3.release()


if __name__ == "__main__":
    unittest.main()