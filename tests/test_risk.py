import tempfile
import unittest
from pathlib import Path

from engine.broker.base import Broker
from engine.config import Config
from engine.models import Analysis, Candle, ClosedTrade, Position, Side, Ticker
from engine.risk.manager import RiskManager


class FakeBroker(Broker):
    def __init__(self, equity=1000.0, cash=1000.0):
        self.cfg = Config()
        self._equity = equity
        self._cash = cash
        self._positions: dict[str, Position] = {}

    @property
    def mode(self):
        return "fake"

    def fetch_candles(self, symbol, timeframe, limit=300):
        return []

    def fetch_ticker(self, symbol):
        return Ticker(symbol=symbol, last=self._equity, bid=self._equity, ask=self._equity)

    def get_balance(self):
        return {"cash": self._cash, "quote": "USDT"}

    def get_positions(self):
        return list(self._positions.values())

    def open_position(self, symbol, side, qty, price, stop, target, conviction, reason):
        p = Position(symbol, side, qty, price, stop, target, 0, conviction, reason)
        self._positions[symbol] = p
        return p

    def close_position(self, position, price, reason):
        trade = ClosedTrade.from_position(position, price, reason)
        self._positions.pop(position.symbol, None)
        return trade

    def update_position(self, position, stop=None, target=None):
        return position

    def mark_to_market(self):
        return self._equity

    def equity(self):
        return self._equity

    def set_cash(self, cash):
        self._cash = cash
        self._equity = cash

    def set_equity(self, equity):
        self._equity = equity


def long_analysis(price=100.0, stop_pct=0.03, conviction=8):
    return Analysis(symbol="BTC/USDT", direction="long", score=1.8, conviction=conviction,
                    price=price, atr_pct=0.02, stop_pct=stop_pct,
                    signals=[{"name": "trend", "side": "long", "weight": 1.5}],
                    factors={})


def make_cfg(**overrides):
    cfg = Config()
    cfg.data_dir = Path(tempfile.mkdtemp(prefix="atlas-test-"))
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class TestRiskSizing(unittest.TestCase):
    def test_risk_amount_honored_when_cap_loose(self):
        cfg = make_cfg(start_balance=1000, risk_per_trade=0.02, max_position_pct=0.70,
                       cash_reserve=0.20, stop_pct=0.03, take_profit_rr=1.5)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.03))
        self.assertTrue(sized["ok"])
        expected = 1000 * 0.02 / (0.03 * 100)
        self.assertAlmostEqual(sized["qty"], expected, places=4)
        self.assertAlmostEqual(sized["risk_amount"], 20.0, places=3)

    def test_max_position_cap_binds(self):
        cfg = make_cfg(risk_per_trade=0.02, max_position_pct=0.08)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.03))
        self.assertTrue(sized["ok"])
        self.assertAlmostEqual(sized["qty"], 0.8, places=4)
        self.assertLessEqual(sized["notional"], 1000 * 0.08 + 1e-6)

    def test_max_position_cap(self):
        cfg = make_cfg(risk_per_trade=0.50, max_position_pct=0.08)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.003))
        self.assertTrue(sized["ok"])
        self.assertLessEqual(sized["notional"], 1000 * 0.08 + 1e-6)

    def test_cash_reserve_respected(self):
        cfg = make_cfg(start_balance=1000, cash_reserve=0.90, risk_per_trade=0.02)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.03))
        self.assertTrue(sized["ok"])
        cost = sized["qty"] * sized["entry"] * 1.001
        self.assertLessEqual(cost, 1000 - 900 + 1e-6)

    def test_stop_out_of_bounds(self):
        cfg = make_cfg()
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.5))
        self.assertFalse(sized["ok"])

    def test_invalid_direction(self):
        cfg = make_cfg()
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        a = long_analysis()
        a.direction = "neutral"
        sized = risk.size_position(a)
        self.assertFalse(sized["ok"])


class TestRiskHardStops(unittest.TestCase):
    def test_drawdown_halt(self):
        cfg = make_cfg(drawdown_halt=0.10)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.run_cycle_hooks(1000)
        risk.run_cycle_hooks(895)
        self.assertFalse(risk.can_trade()[0])
        self.assertEqual(risk.operate_mode(), "halt")
        self.assertTrue(risk.state["halt_reason"].startswith("drawdown"))

    def test_daily_loss_halt(self):
        cfg = make_cfg(daily_loss_limit=0.03)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.run_cycle_hooks(1000)
        risk.record_trade_result(-40.0)
        ok, reason = risk.can_trade()
        self.assertFalse(ok)
        self.assertIn("halt", reason)

    def test_cooldown_on_loss(self):
        cfg = make_cfg(cooldown_minutes=30)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.record_trade_result(-5.0)
        ok, reason = risk.can_trade()
        self.assertFalse(ok)
        self.assertIn("cooldown", reason)

    def test_profit_no_cooldown(self):
        cfg = make_cfg(cooldown_minutes=30)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.record_trade_result(10.0)
        ok, reason = risk.can_trade()
        self.assertTrue(ok)


class TestRiskModes(unittest.TestCase):
    def test_defensive_mode_shrinks_size(self):
        cfg = make_cfg(risk_per_trade=0.02, max_position_pct=0.70, defensive_size_factor=0.6,
                       defensive_drawdown_threshold=0.03)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.run_cycle_hooks(1000)
        broker.set_equity(960)
        self.assertEqual(risk.operate_mode(), "defensive")
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.03))
        expected = 960 * 0.70 * 0.6 / 100
        self.assertAlmostEqual(sized["qty"], expected, places=3)
        self.assertLessEqual(sized["qty"] * sized["entry"] * sized["stop_pct"], 960 * 0.02 + 1e-6)

    def test_defensive_conviction_floor_raised(self):
        cfg = make_cfg(min_conviction=7, defensive_min_conviction=8, defensive_drawdown_threshold=0.03)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.run_cycle_hooks(1000)
        broker.set_equity(960)
        self.assertEqual(risk.operate_mode(), "defensive")
        self.assertEqual(risk.min_conviction_floor(), 8)

    def test_normal_conviction_floor(self):
        cfg = make_cfg(min_conviction=7, defensive_min_conviction=8)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        self.assertEqual(risk.min_conviction_floor(), 7)

    def test_aggressive_clamped_to_hard_cap(self):
        cfg = make_cfg(risk_per_trade=0.02, max_position_pct=0.08, aggressive_enabled=True,
                       aggressive_size_factor=1.2, defensive_drawdown_threshold=0.03)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.run_cycle_hooks(1000)
        self.assertEqual(risk.operate_mode(), "aggressive")
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.03))
        self.assertLessEqual(sized["notional"], 1000 * 0.08 + 1e-6)
        self.assertLessEqual(sized["qty"] * sized["entry"] * sized["stop_pct"], 1000 * 0.02 + 1e-6)

    def test_effective_risk_never_exceeds_budget_even_aggressive(self):
        cfg = make_cfg(risk_per_trade=0.02, max_position_pct=0.70, aggressive_enabled=True,
                       aggressive_size_factor=3.0)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.run_cycle_hooks(1000)
        sized = risk.size_position(long_analysis(price=100, stop_pct=0.08))
        effective = sized["qty"] * sized["entry"] * sized["stop_pct"]
        self.assertLessEqual(effective, 1000 * 0.02 + 1e-6)


class TestCorrelationCap(unittest.TestCase):
    def test_correlation_cap_blocks_at_threshold(self):
        cfg = make_cfg(max_positions=10, correlated_exposure_cap=0.20)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        broker.open_position("BTC/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        ok, _ = risk.can_open_more()
        self.assertTrue(ok)
        broker.open_position("ETH/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        ok, reason = risk.can_open_more()
        self.assertFalse(ok)
        self.assertIn("correlated", reason)

    def test_default_correlation_cap(self):
        cfg = make_cfg(max_positions=10)
        self.assertAlmostEqual(cfg.correlated_exposure_cap, 0.20, places=4)

    def test_drawdown_halt_beats_defensive(self):
        cfg = make_cfg(drawdown_halt=0.10, defensive_drawdown_threshold=0.03)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        risk.run_cycle_hooks(1000)
        broker.set_equity(895)
        risk.run_cycle_hooks(895)
        self.assertEqual(risk.operate_mode(), "halt")
        self.assertFalse(risk.risk_enabled())


class TestMaxPositions(unittest.TestCase):
    def test_position_limit(self):
        cfg = make_cfg(max_positions=2)
        broker = FakeBroker(equity=1000, cash=1000)
        risk = RiskManager(cfg, broker)
        broker.open_position("BTC/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        broker.open_position("ETH/USDT", Side.LONG, 1, 100, 90, 120, 8, "t")
        broker.set_cash(600)
        ok, _ = risk.can_open_more()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()