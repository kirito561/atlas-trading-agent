from __future__ import annotations

import copy
import logging
import shutil
import tempfile
from pathlib import Path
from statistics import mean

from .alerts.notifier import Notifier
from .analysis.sentiment import SentimentAnalyzer
from .broker.paper import PaperBroker
from .config import Config
from .data import SynthData
from .engine import Engine
from .memory.storage import Store
from .models import Ticker
from .risk.manager import RiskManager

log = logging.getLogger("atlas.backtest")


class HistoryFetcher:
    def __init__(self, candles: list) -> None:
        self.candles = candles
        self.idx = 0

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list:
        start = max(0, self.idx + 1 - limit)
        end = self.idx + 1
        return self.candles[start:end]

    def fetch_ticker(self, symbol: str) -> Ticker:
        c = self.candles[min(self.idx, len(self.candles) - 1)]
        return Ticker(symbol=symbol, last=c.close, bid=c.close, ask=c.close)


def load_history(symbol: str, timeframe: str, days: int, source: str = "live", seed: int = 42) -> list:
    if source == "synth":
        return SynthData(seed=seed).fetch_candles(symbol, timeframe, limit=max(400, days * 24))
    try:
        from .data import BybitData
        limit = min(days * 24 + 50, 1000)
        candles = BybitData().fetch_candles(symbol, timeframe, limit)
        if len(candles) < 260:
            raise RuntimeError("too few candles from live source")
        return candles
    except Exception as e:
        log.warning("live history failed, falling back to synthetic: %s", e)
        return SynthData(seed=seed).fetch_candles(symbol, timeframe, limit=max(400, days * 24))


def run_backtest(cfg: Config, symbol: str, days: int = 60, source: str = "live",
                 seed: int = 42, quiet: bool = True) -> dict:
    if not quiet:
        logging.basicConfig(level=logging.INFO)
    candles = load_history(symbol, cfg.backtest_timeframe, days, source, seed)
    used_source = source
    work_dir = Path(tempfile.mkdtemp(prefix="atlas_backtest_"))
    try:
        cfg = copy.copy(cfg)
        cfg.data_dir = work_dir
        cfg.check_stale = False
        cfg.sentiment_enabled = False
        cfg.mode = "paper"
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        fetcher = HistoryFetcher(candles)
        broker = PaperBroker(cfg, fetcher=fetcher)
        risk = RiskManager(cfg, broker)
        store = Store(cfg)
        notifier = Notifier(cfg)
        sentiment = SentimentAnalyzer(enabled=False)
        engine = Engine(cfg, broker, risk, store, notifier, sentiment)

        warmup = 260
        n = len(candles)
        equity_start = cfg.start_balance
        equity_curve: list[float] = []
        trades: list[dict] = []
        for i in range(warmup, n - 1):
            fetcher.idx = i
            risk.state["peak_equity"] = max(risk.state["peak_equity"], broker.equity())
            try:
                result = engine.cycle()
            except Exception as e:
                log.warning("backtest bar %d failed: %s", i, e)
                continue
            trades.extend(result["exits"])
            equity_curve.append(broker.equity())
            if risk.state.get("halted", False):
                break

        return _stats(trades, equity_curve, equity_start, cfg, used_source, len(candles))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _stats(trades: list[dict], equity_curve: list[float], start: float,
           cfg: Config, source: str, bars: int) -> dict:
    total = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    final = equity_curve[-1] if equity_curve else start
    peak = start
    max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    gross = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross / gross_loss if gross_loss > 0 else (gross if gross > 0 else 0.0)
    avg_win = mean(t["pnl"] for t in wins) if wins else 0.0
    avg_loss = mean(t["pnl"] for t in losses) if losses else 0.0
    avg_rr = (avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev > 0:
            returns.append(equity_curve[i] / prev - 1)
    sharpe = 0.0
    if returns:
        m = mean(returns)
        sd = (sum((r - m) ** 2 for r in returns) / max(1, len(returns) - 1)) ** 0.5
        if sd > 0:
            sharpe = round((m / sd) * (24 ** 0.5), 2)
    return {
        "symbol": trades[0]["symbol"] if trades else "",
        "source": source,
        "bars": bars,
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 2) if total else 0.0,
        "start_equity": round(start, 2),
        "final_equity": round(final, 2),
        "total_return_pct": round((final / start - 1) * 100, 2) if start else 0.0,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "net_pnl": round(final - start, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_rr": round(avg_rr, 2),
        "sharpe": sharpe,
        "trades_list": trades[-50:],
        "equity_curve": [round(e, 2) for e in equity_curve[:: max(1, len(equity_curve) // 500)]],
    }