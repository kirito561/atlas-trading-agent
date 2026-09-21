from __future__ import annotations

import time

from ..analysis.technical import Analysis
from ..broker.base import Broker
from ..config import Config, load_state, save_state
from ..models import Side


class RiskManager:
    def __init__(self, cfg: Config, broker: Broker) -> None:
        self.cfg = cfg
        self.broker = broker
        state = load_state(cfg)
        state.setdefault("peak_equity", 0.0)
        state.setdefault("day", "")
        state.setdefault("day_pnl", 0.0)
        state.setdefault("halted", False)
        state.setdefault("halt_reason", "")
        state.setdefault("cooldown_until", 0)
        state.setdefault("daily_loss_triggered", False)
        self.state = state

    def _persist(self) -> None:
        save_state(self.cfg, self.state)

    def run_cycle_hooks(self, equity: float) -> None:
        self._rollover_day()
        self._update_peak(equity)
        self._check_drawdown(equity)
        self._check_daily_loss()
        self._persist()

    def _rollover_day(self) -> None:
        from ..analysis.sentiment import utc_day
        today = utc_day()
        if self.state["day"] != today:
            self.state["day"] = today
            self.state["day_pnl"] = 0.0
            self.state["daily_loss_triggered"] = False
            if self.state.get("halt_reason", "").startswith("daily_loss"):
                self._unhalt()

    def _unhalt(self) -> None:
        self.state["halted"] = False
        self.state["halt_reason"] = ""
        self.state["cooldown_until"] = 0

    def clear_halt(self) -> None:
        if self.state.get("halted") and self.state.get("halt_reason") == "kill_switch":
            self._unhalt()
            self._persist()

    def _update_peak(self, equity: float) -> None:
        if equity > self.state["peak_equity"]:
            self.state["peak_equity"] = equity

    def drawdown(self) -> float:
        peak = self.state.get("peak_equity", 0.0)
        if peak <= 0:
            return 0.0
        return (peak - self.broker.equity()) / peak

    def _check_drawdown(self, equity: float) -> None:
        peak = self.state.get("peak_equity", 0.0)
        if peak > 0 and (peak - equity) / peak >= self.cfg.drawdown_halt:
            self._set_halt("drawdown_halt")

    def _check_daily_loss(self) -> None:
        peak = self.state.get("peak_equity", 0.0)
        if peak > 0 and self.state["day_pnl"] / peak <= -self.cfg.daily_loss_limit:
            self._set_halt("daily_loss_limit")

    def _set_halt(self, reason: str) -> None:
        self.state["halted"] = True
        self.state["halt_reason"] = reason
        self.state["daily_loss_triggered"] = True

    def equity(self) -> float:
        return self.broker.equity()

    def operate_mode(self) -> str:
        if self.state.get("halted", False):
            return "halt"
        dd = self.drawdown()
        if dd >= self.cfg.drawdown_halt:
            return "halt"
        peak = self.state.get("peak_equity", 0.0)
        day_loss_ratio = self.state["day_pnl"] / peak if peak > 0 else 0.0
        if dd >= self.cfg.defensive_drawdown_threshold or day_loss_ratio <= -self.cfg.day_loss_defensive_threshold:
            return "defensive"
        if self.cfg.aggressive_enabled and dd < 0.01 and day_loss_ratio >= 0.0:
            return "aggressive"
        return "normal"

    def min_conviction_floor(self) -> int:
        if self.operate_mode() == "defensive":
            return max(self.cfg.min_conviction, self.cfg.defensive_min_conviction)
        return self.cfg.min_conviction

    def _cap_factor(self) -> float:
        mode = self.operate_mode()
        if mode == "aggressive":
            return self.cfg.aggressive_size_factor
        if mode == "defensive":
            return self.cfg.defensive_size_factor
        return 1.0

    def risk_enabled(self) -> bool:
        return not self.state.get("halted", False)

    def can_trade(self) -> tuple[bool, str]:
        if self.state.get("halted", False):
            return False, f"halted: {self.state.get('halt_reason', 'unknown')}"
        if self.state.get("cooldown_until", 0) > time.time():
            return False, "cooldown active after loss"
        return True, "ok"

    def size_position(self, analysis: Analysis) -> dict:
        entry = analysis.price
        stop_dist_pct = analysis.stop_pct
        stop = 0.0
        if analysis.direction == "long":
            stop = entry * (1 - stop_dist_pct)
        elif analysis.direction == "short":
            stop = entry * (1 + stop_dist_pct)
        else:
            return {"ok": False, "reason": "no direction"}

        if stop_dist_pct < 0.003 or stop_dist_pct > 0.15:
            return {"ok": False, "reason": f"stop distance {stop_dist_pct:.3f} out of bounds"}

        portfolio = self.equity()
        if portfolio <= 0:
            return {"ok": False, "reason": "zero equity"}
        risk_amount = portfolio * self.cfg.risk_per_trade
        qty = risk_amount / (stop_dist_pct * entry)

        max_notional = portfolio * self.cfg.max_position_pct * self._cap_factor()
        qty = min(qty, max_notional / entry)

        notional = qty * entry
        cost = notional * (1 + self.cfg.fee_rate)
        cash = float(self.broker.get_balance().get("cash", 0.0))
        reserve = portfolio * self.cfg.cash_reserve
        free = cash - reserve
        if cost > free:
            if cost > cash:
                qty = 0.0
            else:
                qty = qty * (free / cost)
                notional = qty * entry
                cost = notional * (1 + self.cfg.fee_rate)
        if qty <= 0:
            return {"ok": False, "reason": "insufficient funds after cash reserve"}
        if qty * entry <= 0:
            return {"ok": False, "reason": "position too small"}

        effective_risk = qty * entry * stop_dist_pct
        if effective_risk > risk_amount * 1.0001:
            return {"ok": False, "reason": "effective risk would exceed risk budget"}

        rr = self.cfg.take_profit_rr
        target = entry * (1 + rr * stop_dist_pct) if analysis.direction == "long" else entry * (1 - rr * stop_dist_pct)
        return {
            "ok": True,
            "qty": qty,
            "entry": entry,
            "stop": stop,
            "target": target,
            "notional": qty * entry,
            "risk_amount": risk_amount,
            "stop_pct": stop_dist_pct,
        }

    def can_open_more(self) -> tuple[bool, str]:
        positions = self.broker.get_positions()
        if len(positions) >= self.cfg.max_positions:
            return False, f"max positions {self.cfg.max_positions} reached"
        invested = sum(p.notional for p in positions)
        portfolio = self.equity()
        if portfolio <= 0:
            return False, "zero equity"
        from .portfolio import portfolio_summary
        if invested / portfolio >= 0.5:
            return False, "correlated exposure cap reached"
        return True, "ok"

    def record_trade_result(self, pnl: float) -> None:
        self.state["day_pnl"] = self.state.get("day_pnl", 0.0) + pnl
        peak = self.state.get("peak_equity", 0.0)
        if peak > 0 and self.state["day_pnl"] / peak <= -self.cfg.daily_loss_limit:
            self._set_halt("daily_loss_limit")
        elif pnl < 0:
            self.state["cooldown_until"] = time.time() + self.cfg.cooldown_minutes * 60
        self._persist()

    def reset(self) -> None:
        self.state = {
            "peak_equity": 0.0,
            "day": "",
            "day_pnl": 0.0,
            "halted": False,
            "halt_reason": "",
            "cooldown_until": 0,
            "daily_loss_triggered": False,
        }
        self._persist()