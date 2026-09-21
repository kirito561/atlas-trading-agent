from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class ExitReason(str, Enum):
    STOP = "stop"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    THESIS_INVALID = "thesis_invalid"
    TIME_EXIT = "time_exit"
    RISK_HALT = "risk_halt"
    MANUAL = "manual"


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ccxt(cls, row: list) -> "Candle":
        return cls(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )


@dataclass
class Ticker:
    symbol: str
    last: float
    bid: float
    ask: float
    change_pct: float = 0.0
    volume_24h: float = 0.0
    timestamp: int = 0


@dataclass
class Analysis:
    symbol: str
    direction: str
    score: float
    conviction: int
    price: float
    atr_pct: float
    stop_pct: float
    signals: list[dict] = field(default_factory=list)
    factors: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "score": self.score,
            "conviction": self.conviction,
            "price": self.price,
            "atr_pct": self.atr_pct,
            "stop_pct": self.stop_pct,
            "signals": self.signals,
            "factors": self.factors,
        }


@dataclass
class Position:
    symbol: str
    side: Side
    qty: float
    entry: float
    stop: float
    target: float
    opened_at: int
    conviction: int = 0
    reason: str = ""
    last_price: float = 0.0
    bars_held: int = 0

    @property
    def notional(self) -> float:
        return self.qty * self.entry

    def market_value(self, price: float | None = None) -> float:
        price = price if price is not None and price else (self.last_price or self.entry)
        if not price:
            return 0.0
        if self.side == Side.LONG:
            return self.qty * price
        return self.qty * (2 * self.entry - price)

    def unrealized_pnl(self, price: float | None = None) -> float:
        price = price if price is not None else self.last_price
        if not price:
            return 0.0
        if self.side == Side.LONG:
            return (price - self.entry) * self.qty
        return (self.entry - price) * self.qty

    def unrealized_pct(self) -> float:
        if not self.entry:
            return 0.0
        pnl = self.unrealized_pnl()
        return pnl / (self.qty * self.entry)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "last_price": self.last_price,
            "unrealized_pnl": self.unrealized_pnl(),
            "unrealized_pct": self.unrealized_pct(),
            "opened_at": self.opened_at,
            "bars_held": self.bars_held,
            "conviction": self.conviction,
            "reason": self.reason,
        }


@dataclass
class ClosedTrade:
    id: str
    symbol: str
    side: Side
    qty: float
    entry: float
    exit: float
    pnl: float
    pnl_pct: float
    reason: ExitReason
    conviction: int
    opened_at: int
    closed_at: int

    @classmethod
    def from_position(cls, p: Position, exit_price: float, reason: ExitReason,
                      fee_rate: float = 0.0) -> "ClosedTrade":
        gross = p.unrealized_pnl(exit_price)
        notional = p.qty * p.entry
        fees = notional * fee_rate * 2
        pnl = gross - fees
        pnl_pct = pnl / notional if notional else 0.0
        return cls(
            id=uuid.uuid4().hex[:12],
            symbol=p.symbol,
            side=p.side,
            qty=p.qty,
            entry=p.entry,
            exit=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
            conviction=p.conviction,
            opened_at=p.opened_at,
            closed_at=int(time.time()),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "entry": self.entry,
            "exit": self.exit,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "reason": self.reason.value,
            "conviction": self.conviction,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
        }