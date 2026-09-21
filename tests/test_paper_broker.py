import tempfile
import unittest
from pathlib import Path

from engine.broker.paper import PaperBroker
from engine.config import Config
from engine.models import ExitReason, Side


def make_cfg(tmp: Path) -> Config:
    cfg = Config()
    cfg.data_dir = tmp
    cfg.mode = "paper"
    cfg.start_balance = 1000.0
    return cfg


class TestPaperBroker(unittest.TestCase):
    def test_long_buy_sell_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = PaperBroker(make_cfg(Path(tmp)))
            balance = broker.get_balance()
            self.assertAlmostEqual(balance["cash"], 1000.0)
            p = broker.open_position("BTC/USDT", Side.LONG, 1.0, 100.0, 90.0, 120.0, 8, "test")
            self.assertAlmostEqual(p.entry, 100.0 * 1.0005, places=5)
            self.assertLess(broker.get_balance()["cash"], 900.0)
            trade = broker.close_position(p, 110.0, ExitReason.TAKE_PROFIT.value)
            self.assertGreater(trade.pnl, 9.0)
            self.assertLess(trade.pnl, 11.0)
            self.assertEqual(len(broker.get_positions()), 0)

    def test_short_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            cfg.allow_short = True
            broker = PaperBroker(cfg)
            p = broker.open_position("ETH/USDT", Side.SHORT, 1.0, 100.0, 110.0, 80.0, 8, "test")
            trade = broker.close_position(p, 90.0, ExitReason.TAKE_PROFIT.value)
            self.assertGreater(trade.pnl, 8.0)

    def test_stop_loss_is_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = PaperBroker(make_cfg(Path(tmp)))
            p = broker.open_position("BTC/USDT", Side.LONG, 1.0, 100.0, 97.0, 120.0, 8, "test")
            trade = broker.close_position(p, 97.0, ExitReason.STOP.value)
            self.assertLess(trade.pnl, 0.0)

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            broker = PaperBroker(cfg)
            p = broker.open_position("BTC/USDT", Side.LONG, 2.0, 50.0, 45.0, 60.0, 7, "test")
            broker2 = PaperBroker(cfg)
            positions = broker2.get_positions()
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0].symbol, p.symbol)
            self.assertAlmostEqual(positions[0].qty, 2.0)

    def test_update_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = PaperBroker(make_cfg(Path(tmp)))
            p = broker.open_position("BTC/USDT", Side.LONG, 1.0, 100.0, 90.0, 120.0, 8, "test")
            updated = broker.update_position(p, stop=95.0)
            self.assertAlmostEqual(updated.stop, 95.0)
            self.assertAlmostEqual(broker.position_for("BTC/USDT").stop, 95.0)


if __name__ == "__main__":
    unittest.main()