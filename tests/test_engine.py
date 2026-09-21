import tempfile
import unittest
from pathlib import Path

from engine.alerts.notifier import Notifier
from engine.broker.base import Broker
from engine.config import Config
from engine.engine import Engine
from engine.memory.storage import Store
from engine.models import ClosedTrade, ExitReason, Position, Side, Ticker
from engine.risk.manager import RiskManager


class FakeBroker(Broker):
    def __init__(self, cfg):
        super().__init__(cfg)
        self._equity = cfg.start_balance
        self._cash = cfg.start_balance
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
        exit_reason = ExitReason(reason) if reason in ExitReason._value2member_map_ else ExitReason.MANUAL
        trade = ClosedTrade.from_position(position, price, exit_reason)
        self._positions.pop(position.symbol, None)
        return trade

    def update_position(self, position, stop=None, target=None):
        return position

    def mark_to_market(self):
        return self._equity

    def equity(self):
        return self._equity


def make_cfg(reason=None, **overrides):
    cfg = Config()
    cfg.data_dir = Path(tempfile.mkdtemp(prefix="atlas-engine-"))
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def make_engine(cfg=None, reason=None):
    cfg = cfg or make_cfg()
    broker = FakeBroker(cfg)
    broker.open_position("BTC/USDT", Side.LONG, 1, 100, 90, 120, 8, "test")
    risk = RiskManager(cfg, broker)
    store = Store(cfg)
    notifier = Notifier(cfg)
    return Engine(cfg, broker, risk, store, notifier), broker, risk


class TestKillSwitch(unittest.TestCase):
    def test_kill_switch_closes_and_halts(self):
        cfg = make_cfg()
        engine, broker, risk = make_engine(cfg)
        cfg.kill_switch_file.write_text("engaged", encoding="utf-8")
        result = engine.cycle()
        self.assertTrue(risk.state["halted"])
        self.assertEqual(risk.state["halt_reason"], "kill_switch")
        self.assertEqual(broker.get_positions(), [])
        self.assertEqual(result["entries"], [])

    def test_no_kill_switch_runs_normally(self):
        cfg = make_cfg()
        engine, broker, risk = make_engine(cfg)
        result = engine.cycle()
        self.assertFalse(risk.state["halted"])

    def test_clearing_kill_switch_unhalts_after_cycle(self):
        cfg = make_cfg()
        engine, broker, risk = make_engine(cfg)
        cfg.kill_switch_file.write_text("engaged", encoding="utf-8")
        engine.cycle()
        self.assertTrue(risk.state["halted"])
        cfg.kill_switch_file.unlink()
        engine.cycle()
        self.assertFalse(risk.state["halted"])


if __name__ == "__main__":
    unittest.main()