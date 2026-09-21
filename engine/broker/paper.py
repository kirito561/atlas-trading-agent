from __future__ import annotations

import json
import time

from ..config import Config, load_state, save_state
from ..models import ClosedTrade, Candle, ExitReason, Position, Side, Ticker
from .base import Broker

FEE_RATE_DEFAULT = 0.001
SLIPPAGE_DEFAULT = 0.0005
FUNDING_PERIOD_HOURS = 8.0


class PaperBroker(Broker):
    def __init__(self, cfg: Config, fetcher=None) -> None:
        super().__init__(cfg)
        self._cash = cfg.start_balance
        self._positions: dict[str, Position] = {}
        self._fetcher = fetcher
        self.fee_rate = cfg.fee_rate
        self.slippage = cfg.slippage
        self.reconcile()
        self._persist()

    @property
    def mode(self) -> str:
        return "paper"

    def _load(self) -> None:
        if self.cfg.positions_file.exists():
            try:
                raw = json.loads(self.cfg.positions_file.read_text(encoding="utf-8"))
                self._cash = float(raw.get("cash", self.cfg.start_balance))
                for p in raw.get("positions", {}).values():
                    position = Position(
                        symbol=p["symbol"],
                        side=Side(p["side"]),
                        qty=float(p["qty"]),
                        entry=float(p["entry"]),
                        stop=float(p["stop"]),
                        target=float(p["target"]),
                        opened_at=int(p["opened_at"]),
                        conviction=int(p.get("conviction", 0)),
                        reason=p.get("reason", ""),
                        bars_held=int(p.get("bars_held", 0)),
                    )
                    self._positions[position.symbol] = position
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                pass

    def reconcile(self) -> dict:
        seen = set(self._positions)
        self._load()
        adopted = [s for s in self._positions if s not in seen]
        return {"adopted": adopted, "orphans": [], "dropped": []}

    def _persist(self) -> None:
        data = {
            "cash": self._cash,
            "positions": {s: p.to_dict() for s, p in self._positions.items()},
        }
        tmp = self.cfg.positions_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.cfg.positions_file)

    def _reset_references(self) -> None:
        if self._positions:
            self._positions = {}
        self._cash = self.cfg.start_balance
        self._persist()

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        if self._fetcher is not None:
            return self._fetcher.fetch_candles(symbol, timeframe, limit)
        from ..data import BybitData
        return BybitData(self.cfg).fetch_candles(symbol, timeframe, limit)

    def fetch_ticker(self, symbol: str) -> Ticker:
        if self._fetcher is not None:
            return self._fetcher.fetch_ticker(symbol)
        from ..data import BybitData
        return BybitData(self.cfg).fetch_ticker(symbol)

    def get_balance(self) -> dict:
        return {"cash": round(self._cash, 6), "quote": self.cfg.quote}

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def position_for(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def open_position(self, symbol: str, side: Side, qty: float, price: float,
                      stop: float, target: float, conviction: int, reason: str) -> Position:
        if symbol in self._positions:
            raise ValueError(f"position already open for {symbol}")
        fill = price * (1 + self.slippage) if side == Side.LONG else price * (1 - self.slippage)
        notional = qty * fill
        fee = notional * self.fee_rate
        if side == Side.LONG:
            self._cash -= notional + fee
        else:
            self._cash -= notional + fee
        position = Position(
            symbol=symbol,
            side=side,
            qty=qty,
            entry=fill,
            stop=min(stop, fill) if side == Side.LONG else max(stop, fill),
            target=target,
            opened_at=int(time.time()),
            conviction=conviction,
            reason=reason,
            last_price=fill,
        )
        self._positions[symbol] = position
        self._persist()
        return position

    def _funding_cost(self, position: Position) -> float:
        if self._fetcher is not None:
            hours = max(1.0, position.bars_held)
        else:
            hours = max(0.0, (time.time() - position.opened_at) / 3600.0)
        return position.qty * position.entry * self.cfg.funding_rate * (hours / FUNDING_PERIOD_HOURS)

    def close_position(self, position: Position, price: float, reason: str) -> ClosedTrade:
        fill = price * (1 - self.slippage) if position.side == Side.LONG else price * (1 + self.slippage)
        notional_entry = position.qty * position.entry
        fee = notional_entry * self.fee_rate
        funding = self._funding_cost(position)
        if position.side == Side.LONG:
            self._cash += position.qty * fill - fee - funding
        else:
            pnl = (position.entry - fill) * position.qty
            self._cash += notional_entry + pnl - fee - funding
        self._positions.pop(position.symbol, None)
        trade = ClosedTrade.from_position(position, fill, ExitReason(reason) if reason in ExitReason._value2member_map_ else ExitReason.MANUAL, self.fee_rate)
        trade.pnl -= funding
        trade.pnl_pct = trade.pnl / notional_entry if notional_entry else 0.0
        self._persist()
        return trade

    def flatten(self) -> list[ClosedTrade]:
        closed = []
        for symbol in list(self._positions.keys()):
            position = self._positions[symbol]
            try:
                ticker = self.fetch_ticker(symbol)
                closed.append(self.close_position(position, ticker.last, "risk_halt"))
            except Exception:
                continue
        return closed

    def update_position(self, position: Position, *, stop: float | None = None,
                        target: float | None = None) -> Position:
        stored = self._positions.get(position.symbol)
        if stored is None:
            return position
        if stop is not None:
            stored.stop = stop
        if target is not None:
            stored.target = target
        self._persist()
        return stored

    def mark_to_market(self) -> float:
        equity = self._cash
        updated: dict[str, Position] = {}
        for symbol, position in self._positions.items():
            try:
                ticker = self.fetch_ticker(symbol)
                position.last_price = ticker.last
                position.bars_held += 1
            except Exception:
                position.last_price = position.entry
                position.bars_held += 1
            equity += position.market_value()
            updated[symbol] = position
        self._positions = updated
        return equity

    def equity(self) -> float:
        equity = self._cash
        for p in self._positions.values():
            equity += p.market_value()
        return equity