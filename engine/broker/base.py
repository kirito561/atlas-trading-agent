from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Config
from ..models import ClosedTrade, Candle, Position, Side, Ticker


class Broker(ABC):
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @abstractmethod
    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        ...

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Ticker:
        ...

    @abstractmethod
    def get_balance(self) -> dict:
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        ...

    @abstractmethod
    def open_position(self, symbol: str, side: Side, qty: float, price: float,
                      stop: float, target: float, conviction: int, reason: str) -> Position:
        ...

    @abstractmethod
    def close_position(self, position: Position, price: float, reason: str) -> ClosedTrade:
        ...

    @abstractmethod
    def update_position(self, position: Position, *, stop: float | None = None,
                        target: float | None = None) -> Position:
        ...

    @abstractmethod
    def mark_to_market(self) -> float:
        ...

    @property
    @abstractmethod
    def mode(self) -> str:
        ...