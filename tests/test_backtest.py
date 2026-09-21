import tempfile
import unittest
from pathlib import Path

from engine.backtest import run_backtest
from engine.config import Config


def make_cfg(tmp: Path) -> Config:
    cfg = Config()
    cfg.data_dir = tmp
    cfg.mode = "paper"
    cfg.start_balance = 1000.0
    cfg.watchlist = ["BTC/USDT"]
    cfg.min_conviction = 7
    cfg.trailing_stop = False
    cfg.allow_short = True
    return cfg


class TestBacktest(unittest.TestCase):
    def test_synth_backtest_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            stats = run_backtest(cfg, "BTC/USDT", days=30, source="synth", seed=42)
            self.assertGreaterEqual(stats["trades"], 0)
            self.assertGreater(len(stats["equity_curve"]), 10)
            self.assertAlmostEqual(stats["final_equity"], stats["equity_curve"][-1], delta=0.1)
            self.assertGreater(stats["max_drawdown_pct"], 0.0)
            self.assertIsInstance(stats["win_rate"], float)

    def test_different_seeds_produce_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            a = run_backtest(cfg, "ETH/USDT", days=20, source="synth", seed=1)
            b = run_backtest(cfg, "ETH/USDT", days=20, source="synth", seed=2)
            self.assertGreaterEqual(a["trades"], 0)
            self.assertGreaterEqual(b["trades"], 0)
            self.assertGreater(len(a["equity_curve"]), 0)
            self.assertGreater(len(b["equity_curve"]), 0)


if __name__ == "__main__":
    unittest.main()