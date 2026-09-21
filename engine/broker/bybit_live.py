from __future__ import annotations

import logging

import ccxt

from ..config import Config
from ..models import ClosedTrade, Candle, ExitReason, Position, Side, Ticker
from .base import Broker

log = logging.getLogger("atlas.live")


class BybitLiveBroker(Broker):
    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        if not cfg.bybit_api_key or not cfg.bybit_api_secret:
            raise RuntimeError("ATLAS_MODE=live requires BYBIT_API_KEY and BYBIT_API_SECRET")
        options = {
            "defaultType": "swap",
            "adjustForTimeDifference": True,
        }
        if cfg.bybit_testnet:
            options["sandboxMode"] = True
        self.exchange = ccxt.bybit({
            "apiKey": cfg.bybit_api_key,
            "secret": cfg.bybit_api_secret,
            "enableRateLimit": True,
            "options": options,
        })

    @property
    def mode(self) -> str:
        return "live"

    def _symbol(self, symbol: str) -> str:
        return symbol.replace("USDT", ":USDT").replace("/", "")

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        raw = self.exchange.fetch_ohlcv(self._symbol(symbol), timeframe, limit=limit)
        return [Candle.from_ccxt(row) for row in raw]

    def fetch_ticker(self, symbol: str) -> Ticker:
        t = self.exchange.fetch_ticker(self._symbol(symbol))
        return Ticker(
            symbol=symbol,
            last=float(t["last"]),
            bid=float(t["bid"] or 0),
            ask=float(t["ask"] or 0),
            change_pct=float(t.get("percentage") or 0),
            volume_24h=float(t.get("quoteVolume") or 0),
        )

    def get_balance(self) -> dict:
        balance = self.exchange.fetch_balance({"type": "swap"})
        total = balance.get("total", {})
        return {
            "cash": float(total.get(self.cfg.quote, 0.0)),
            "quote": self.cfg.quote,
        }

    def get_positions(self) -> list[Position]:
        positions = []
        for p in self.exchange.fetch_positions(["swap"]):
            symbol = p["symbol"].split(":")[0] + "/" + self.cfg.quote
            contracts = float(p["contracts"] or 0)
            entry = float(p["entryPrice"] or 0)
            side = Side.LONG if p["side"] == "long" else Side.SHORT
            if contracts <= 0 or entry <= 0:
                continue
            positions.append(Position(
                symbol=symbol,
                side=side,
                qty=abs(contracts),
                entry=entry,
                stop=float(p.get("stopLossPrice") or 0),
                target=float(p.get("takeProfitPrice") or 0),
                opened_at=int((p.get("timestamp") or 0) / 1000),
            ))
        return positions

    def open_position(self, symbol: str, side: Side, qty: float, price: float,
                      stop: float, target: float, conviction: int, reason: str) -> Position:
        market_symbol = self._symbol(symbol)
        try:
            self.exchange.set_leverage(self.cfg.max_leverage, market_symbol)
        except Exception as e:
            raise RuntimeError(f"unable to enforce leverage limit {self.cfg.max_leverage}x: {e}")
        params = {
            "stopLoss": float(stop),
            "takeProfit": float(target),
        }
        order = self.exchange.create_order(
            market_symbol,
            "market",
            "buy" if side == Side.LONG else "sell",
            qty,
            None,
            params,
        )
        fill = float(order.get("average") or price)
        return Position(
            symbol=symbol,
            side=side,
            qty=qty,
            entry=fill,
            stop=stop,
            target=target,
            opened_at=int(order.get("timestamp") or 0) // 1000,
            conviction=conviction,
            reason=reason,
            last_price=fill,
        )

    def close_position(self, position: Position, price: float, reason: str) -> ClosedTrade:
        order = self.exchange.create_order(
            self._symbol(position.symbol),
            "market",
            "sell" if position.side == Side.LONG else "buy",
            position.qty,
        )
        fill = float(order.get("average") or price)
        trade = ClosedTrade.from_position(position, fill, ExitReason.MANUAL, 0.0006)
        trade.reason = ExitReason(reason) if reason in ExitReason._value2member_map_ else ExitReason.MANUAL
        return trade

    def update_position(self, position: Position, *, stop: float | None = None,
                        target: float | None = None) -> Position:
        if stop is None and target is None:
            return position
        orders = self.exchange.fetch_open_orders(self._symbol(position.symbol))
        if not orders:
            raise RuntimeError("no open order to modify; trailing stop update skipped")
        params = {}
        if stop is not None:
            params["stopLoss"] = float(stop)
        if target is not None:
            params["takeProfit"] = float(target)
        order = orders[0]
        self.exchange.edit_order(
            order["id"],
            self._symbol(position.symbol),
            "market",
            order["side"],
            order["amount"],
            None,
            params,
        )
        position.stop = stop if stop is not None else position.stop
        position.target = target if target is not None else position.target
        return position

    def mark_to_market(self) -> float:
        equity = sum(self.exchange.fetch_balance({"type": "swap"}).get("total", {}).values())
        positions = self.get_positions()
        for p in positions:
            try:
                t = self.fetch_ticker(p.symbol)
                p.last_price = t.last
                equity += p.unrealized_pnl(t.last)
            except Exception:
                equity += p.unrealized_pnl()
        return equity