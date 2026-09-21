from __future__ import annotations

import json
import logging
import time

from .alerts.notifier import Notifier
from .analysis.sentiment import SentimentAnalyzer
from .broker.base import Broker
from .config import Config
from .guards import validate_ticker
from .memory.storage import Store
from .models import ExitReason, Position, Side
from .risk.manager import RiskManager
from .risk.portfolio import portfolio_summary
from .strategy import decide_entry, score_symbol

log = logging.getLogger("atlas.engine")


class Engine:
    def __init__(self, cfg: Config, broker: Broker, risk: RiskManager,
                 store: Store, notifier: Notifier, sentiment: SentimentAnalyzer | None = None) -> None:
        self.cfg = cfg
        self.broker = broker
        self.risk = risk
        self.store = store
        self.notifier = notifier
        self.sentiment = sentiment if cfg.sentiment_enabled else (sentiment or None)
        self.running = False
        self._last_mode: str | None = None
        self._kill_notified = False

    def close_engine_positions(self, reason: str) -> None:
        for position in self.broker.get_positions():
            try:
                ticker = self.broker.fetch_ticker(position.symbol)
                self._exit_position(position, ticker.last, ExitReason(reason if reason in ExitReason._value2member_map_ else ExitReason.RISK_HALT))
            except Exception as e:
                log.warning("failed to close %s: %s", position.symbol, e)

    def cycle(self) -> dict:
        result: dict = {"entries": [], "exits": [], "skipped": []}
        try:
            self.broker.reconcile()
        except Exception as e:
            log.warning("reconcile failed: %s", e)
        notify = self._check_kill_switch()
        if notify:
            try:
                self.broker.cancel_all_open_orders()
            except Exception as e:
                log.warning("cancel orders failed: %s", e)
            self.close_engine_positions(ExitReason.RISK_HALT.value)
            equity = self.risk.equity()
            self.risk.run_cycle_hooks(equity)
            self._snapshot(equity)
            self._notify_mode_change()
            return result
        try:
            equity = self.broker.mark_to_market()
        except Exception as e:
            log.warning("mark_to_market failed: %s", e)
            equity = self.risk.equity()

        self.risk.run_cycle_hooks(equity)
        self._manage_positions(result)

        if self.risk.risk_enabled():
            self._scan_and_enter(result)

        self._snapshot(equity)
        self._notify_mode_change()
        return result

    def _check_kill_switch(self) -> bool:
        if self.cfg.kill_switch_file.exists():
            if not self._kill_notified:
                self.notifier.notify("KILL SWITCH engaged - closing all positions and halting.", "critical")
                self._kill_notified = True
            self.risk.state["halted"] = True
            self.risk.state["halt_reason"] = "kill_switch"
            return True
        if self._kill_notified or self.risk.state.get("halt_reason") == "kill_switch":
            self.risk.clear_halt()
        return False

    def _notify_mode_change(self) -> None:
        mode = self.risk.operate_mode()
        if self._last_mode is not None and mode != self._last_mode:
            self.notifier.notify(f"operating mode changed: {self._last_mode} -> {mode}", "warning" if mode in ("defensive", "halt") else "info")
        self._last_mode = mode

    def _scan_and_enter(self, result: dict) -> None:
        candidates: list = []
        held_symbols = {p.symbol for p in self.broker.get_positions()}
        min_cv = self.risk.min_conviction_floor()
        for symbol in self.cfg.watchlist:
            if symbol in held_symbols:
                result["skipped"].append({"symbol": symbol, "reason": "position already open"})
                self.store.record_decision(symbol, "skip", 0, {"reason": "position already open"})
                continue
            try:
                analysis, why = score_symbol(self.broker, self.sentiment, symbol, self.cfg,
                                             self.cfg.trend_timeframe)
            except Exception as e:
                log.warning("scan %s failed: %s", symbol, e)
                continue
            if analysis is None:
                reason = why or "insufficient data"
                result["skipped"].append({"symbol": symbol, "reason": reason})
                self.store.record_decision(symbol, "skip", 0, {"reason": reason})
                continue
            if analysis.conviction < min_cv:
                why = f"conviction {analysis.conviction} below defensive floor {min_cv}"
                result["skipped"].append({"symbol": symbol, "reason": why})
                self.store.record_decision(symbol, "skip", analysis.conviction,
                                           {"reason": why, "score": analysis.score,
                                            "direction": analysis.direction})
                continue
            ok, why = decide_entry(analysis, self.cfg)
            if not ok:
                result["skipped"].append({"symbol": symbol, "reason": why})
                self.store.record_decision(symbol, "skip", analysis.conviction,
                                           {"reason": why, "score": analysis.score,
                                            "direction": analysis.direction})
                continue
            candidates.append(analysis)

        if not candidates:
            return

        can_open, reason = self.risk.can_open_more()
        if not can_open:
            for a in candidates:
                self.store.record_decision(a.symbol, "skip", a.conviction, {"reason": reason})
                result["skipped"].append({"symbol": a.symbol, "reason": reason})
            return

        candidates.sort(key=lambda a: a.conviction, reverse=True)
        for analysis in candidates:
            trade_ok, trade_reason = self.risk.can_trade()
            if not trade_ok:
                self.store.record_decision(analysis.symbol, "skip", analysis.conviction,
                                           {"reason": trade_reason})
                continue
            open_ok, open_reason = self.risk.can_open_more()
            if not open_ok:
                self.store.record_decision(analysis.symbol, "skip", analysis.conviction,
                                           {"reason": open_reason})
                continue
            sized = self.risk.size_position(analysis)
            if not sized.get("ok"):
                self.store.record_decision(analysis.symbol, "skip", analysis.conviction,
                                           {"reason": sized.get("reason")})
                result["skipped"].append({"symbol": analysis.symbol, "reason": sized.get("reason")})
                continue
            try:
                ticker = self.broker.fetch_ticker(analysis.symbol)
                valid, guard_reason = validate_ticker(ticker, self.cfg)
            except Exception as e:
                log.warning("ticker %s failed: %s", analysis.symbol, e)
                continue
            if not valid:
                self.store.record_decision(analysis.symbol, "skip", analysis.conviction,
                                           {"reason": guard_reason})
                result["skipped"].append({"symbol": analysis.symbol, "reason": guard_reason})
                continue
            side = Side.LONG if analysis.direction == "long" else Side.SHORT
            try:
                position = self.broker.open_position(
                    analysis.symbol, side, sized["qty"], sized["entry"],
                    sized["stop"], sized["target"], analysis.conviction,
                    "; ".join(s["name"] for s in analysis.signals[:4]),
                )
            except Exception as e:
                log.warning("open %s failed: %s", analysis.symbol, e)
                self.store.record_decision(analysis.symbol, "error", analysis.conviction,
                                           {"error": str(e)})
                continue
            self.store.record_decision(analysis.symbol, "enter", analysis.conviction, analysis.to_dict() | sized)
            result["entries"].append(position.to_dict())
            self.notifier.notify(
                f"ENTER {analysis.symbol} {side.value.upper()} qty={position.qty:.4f} "
                f"@ {position.entry:.4f} stop={position.stop:.4f} target={position.target:.4f} "
                f"conviction={analysis.conviction}/10", "info")

    def _manage_positions(self, result: dict) -> None:
        for position in list(self.broker.get_positions()):
            try:
                ticker = self.broker.fetch_ticker(position.symbol)
            except Exception as e:
                log.warning("ticker %s failed: %s", position.symbol, e)
                continue
            position.bars_held += 1
            direction = "long" if position.side == Side.LONG else "short"
            if direction == "long":
                if ticker.last <= position.stop:
                    self._exit_position(position, position.stop, ExitReason.STOP, result)
                    continue
                if ticker.last >= position.target:
                    self._exit_position(position, position.target, ExitReason.TAKE_PROFIT, result)
                    continue
            else:
                if ticker.last >= position.stop:
                    self._exit_position(position, position.stop, ExitReason.STOP, result)
                    continue
                if ticker.last <= position.target:
                    self._exit_position(position, position.target, ExitReason.TAKE_PROFIT, result)
                    continue

            if position.bars_held > self.cfg.max_hold_bars:
                self._exit_position(position, ticker.last, ExitReason.TIME_EXIT, result)
                continue

            if self.cfg.trail_stop:
                self._apply_trail(position, ticker.last)

    def _apply_trail(self, position: Position, price: float) -> None:
        if position.side == Side.LONG:
            if price > position.entry and (price / position.entry - 1) >= max(self.cfg.trail_pct, 0.01):
                new_stop = max(position.stop, price * (1 - self.cfg.trail_pct))
                if new_stop > position.stop:
                    self.broker.update_position(position, stop=new_stop)
        else:
            if price < position.entry and (1 - price / position.entry) >= max(self.cfg.trail_pct, 0.01):
                new_stop = min(position.stop, price * (1 + self.cfg.trail_pct))
                if new_stop < position.stop:
                    self.broker.update_position(position, stop=new_stop)

    def _exit_position(self, position: Position, price: float, reason: ExitReason, result: dict | None = None) -> None:
        try:
            trade = self.broker.close_position(position, price, reason.value)
        except Exception as e:
            log.warning("close %s failed: %s", position.symbol, e)
            return
        self.store.record_trade(trade)
        self.risk.record_trade_result(trade.pnl)
        if result is not None:
            result["exits"].append(trade.to_dict())
        pnl_pct_of_portfolio = abs(trade.pnl) / self.risk.equity() if self.risk.equity() > 0 else 0.0
        severity = "info"
        if trade.pnl < 0:
            severity = "warning"
            if pnl_pct_of_portfolio >= self.cfg.escalate_loss_pct:
                severity = "critical"
        self.notifier.notify(
            f"EXIT {trade.symbol} {trade.side.value.upper()} qty={trade.qty:.4f} "
            f"@ {trade.exit:.4f} pnl={trade.pnl:.4f} ({trade.pnl_pct * 100:.2f}%) "
            f"reason={trade.reason.value} conviction={trade.conviction}", severity)

    def _snapshot(self, equity: float) -> None:
        cash = float(self.broker.get_balance().get("cash", 0.0))
        mode = self.risk.operate_mode()
        self.store.record_equity(equity, cash, mode)
        self.store.snapshot_positions(self.broker.get_positions())
        try:
            summary = portfolio_summary(self.cfg, self.broker, self.risk, self.risk.state)
            summary["journal"] = self.store.summary()
            summary["operating_mode"] = mode
            tmp = self.cfg.data_dir / "status.json.tmp"
            tmp.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            tmp.replace(self.cfg.data_dir / "status.json")
        except Exception as e:
            log.warning("status snapshot failed: %s", e)

    def status(self) -> dict:
        return portfolio_summary(self.cfg, self.broker, self.risk, self.risk.state)

    def run_forever(self) -> None:
        interval = max(1, self.cfg.interval_minutes) * 60
        self.running = True
        self.notifier.notify(f"ATLAS session started. Mode: {self.cfg.mode}. Interval: {interval // 60}min")
        log.info("ATLAS session started. mode=%s interval=%ss", self.cfg.mode, interval)
        while self.running:
            started = time.time()
            try:
                summary = self.cycle()
                log.info("cycle done entries=%d exits=%d skipped=%d", len(summary["entries"]), len(summary["exits"]), len(summary["skipped"]))
            except Exception as e:
                log.exception("cycle failed: %s", e)
                self.notifier.notify(f"cycle error: {e}", "warning")
            elapsed = time.time() - started
            time.sleep(max(1, interval - elapsed))