from __future__ import annotations

import time

from ..broker.base import Broker
from ..config import Config, load_state, save_state
from .manager import RiskManager


def portfolio_summary(cfg: Config, broker: Broker, risk: RiskManager, state: dict) -> dict:
    positions = broker.get_positions()
    cash = float(broker.get_balance().get("cash", 0.0))
    equity = risk.equity()
    invested = 0.0
    for p in positions:
        invested += p.notional
    exposed = invested / equity if equity else 0.0
    drawdown = risk.drawdown()
    return {
        "mode": cfg.mode,
        "operating_mode": risk.operate_mode(),
        "halted": bool(state.get("halted", False)),
        "halt_reason": state.get("halt_reason", ""),
        "cash": round(cash, 4),
        "quote": cfg.quote,
        "equity": round(equity, 4),
        "peak_equity": round(state.get("peak_equity", equity), 4),
        "drawdown": round(drawdown, 4),
        "invested": round(invested, 4),
        "exposure_pct": round(exposed * 100, 2),
        "cash_reserve_pct": round(max(0.0, cash / equity) * 100, 2) if equity else 0.0,
        "open_positions": len(positions),
        "max_positions": cfg.max_positions,
        "day": state.get("day", ""),
        "day_pnl": round(state.get("day_pnl", 0.0), 4),
        "daily_loss_limit": cfg.daily_loss_limit,
        "risk_per_trade_pct": cfg.risk_per_trade * 100,
    }