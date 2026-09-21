from __future__ import annotations

import argparse
import json
import logging
import sys

from .alerts.notifier import Notifier
from .analysis.sentiment import SentimentAnalyzer
from .broker.base import Broker
from .broker.bybit_live import BybitLiveBroker
from .broker.paper import PaperBroker
from .config import Config
from .data import SynthData
from .lock import InstanceLock
from .memory.storage import Store
from .risk.manager import RiskManager


def with_instance_lock(cfg: Config, hold: bool = True) -> InstanceLock | None:
    lock = InstanceLock(cfg.lock_file)
    return lock if lock.acquire(hold=hold) else None


def make_broker(cfg: Config) -> Broker:
    if cfg.is_live:
        return BybitLiveBroker(cfg)
    return PaperBroker(cfg)


def check_license(cfg: Config) -> tuple[bool, dict]:
    from .license import verify_key
    result = {"required": cfg.license_required, "enforced": False}
    if not cfg.license_required:
        return True, result
    if not cfg.license_key:
        result["enforced"] = True
        return False, result | {"reason": "no license key set"}
    status = verify_key(cfg.license_key, cfg.license_secret)
    result["enforced"] = True
    result["key_status"] = status
    return bool(status.get("valid")), result


def make_engine(cfg: Config):
    from .engine import Engine
    broker = make_broker(cfg)
    risk = RiskManager(cfg, broker)
    store = Store(cfg)
    notifier = Notifier(cfg)
    sentiment = SentimentAnalyzer(enabled=cfg.sentiment_enabled)
    return Engine(cfg, broker, risk, store, notifier, sentiment), risk, broker, store


def cmd_run(cfg: Config, args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ok, status = check_license(cfg)
    if not ok:
        print("refusing to trade: invalid license -> " + json.dumps(status))
        return 1
    lock = with_instance_lock(cfg)
    if lock is None:
        print("refusing to start: another ATLAS instance is already running (data/atlas.lock)")
        return 1
    try:
        engine, _, _, _ = make_engine(cfg)
        engine.run_forever()
    finally:
        lock.release()
    return 0


def cmd_once(cfg: Config, args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ok, status = check_license(cfg)
    if not ok:
        print("refusing to trade: invalid license -> " + json.dumps(status))
        return 1
    lock = with_instance_lock(cfg)
    if lock is None:
        print("refusing to start: another ATLAS instance is already running (data/atlas.lock)")
        return 1
    try:
        engine, risk, broker, store = make_engine(cfg)
        equity = broker.mark_to_market()
        risk.run_cycle_hooks(equity)
        summary = engine.cycle()
        status = engine.status()
        print(json.dumps({"status": status, "cycle": summary}, indent=2))
    finally:
        lock.release()
    return 0


def cmd_backtest(cfg: Config, args) -> int:
    from .backtest import run_backtest
    stats = run_backtest(cfg, args.symbol, days=args.days, source=args.source, quiet=False)
    printable = {k: v for k, v in stats.items() if k not in ("trades_list", "equity_curve")}
    print(json.dumps(printable, indent=2))
    return 0


def cmd_status(cfg: Config, args) -> int:
    engine, risk, broker, store = make_engine(cfg)
    try:
        broker.mark_to_market()
    except Exception as e:
        logging.getLogger("atlas").warning("mark to market failed: %s", e)
    status = engine.status()
    summary = store.summary()
    status["journal"] = summary
    print(json.dumps(status, indent=2))
    return 0


def cmd_history(cfg: Config, args) -> int:
    from .memory.storage import Store
    store = Store(cfg)
    limit = args.limit
    if args.kind in ("trades", "all"):
        print("=== TRADES ===")
        for t in store.recent_trades(limit):
            print(json.dumps(t))
    if args.kind in ("decisions", "all"):
        print("=== DECISIONS ===")
        for d in store.recent_decisions(limit):
            print(json.dumps(d))
    return 0


def cmd_equity(cfg: Config, args) -> int:
    from .memory.storage import Store
    store = Store(cfg)
    for row in store.equity_history(args.limit):
        print(json.dumps(row))
    return 0


def cmd_stats(cfg: Config, args) -> int:
    store = Store(cfg)
    print(json.dumps(store.win_stats(), indent=2))
    return 0


def cmd_kill(cfg: Config, args) -> int:
    if args.off:
        if cfg.kill_switch_file.exists():
            cfg.kill_switch_file.unlink()
            print("kill switch cleared")
        else:
            print("no kill switch active")
        return 0
    cfg.kill_switch_file.write_text("engaged", encoding="utf-8")
    print("kill switch engaged - engine will close all positions and halt on next cycle")
    if cfg.is_live:
        try:
            engine, risk, broker, store = make_engine(cfg)
            broker.cancel_all_open_orders()
            closed = broker.flatten()
            print(f"flattened {len(closed)} live position(s) via exchange")
        except Exception as e:
            print(f"warning: live flatten failed ({e}); engine will close on next cycle")
    return 0


def cmd_reset(cfg: Config, args) -> int:
    if not args.yes:
        print("refusing to reset without --yes")
        return 1
    lock = with_instance_lock(cfg)
    if lock is None:
        print("refusing to reset: another ATLAS instance is running")
        return 1
    try:
        engine, risk, broker, store = make_engine(cfg)
        risk.reset()
        if cfg.positions_file.exists():
            cfg.positions_file.unlink()
        if cfg.db_file.exists():
            cfg.db_file.unlink()
        print("reset complete")
    finally:
        lock.release()
    return 0


def cmd_license(cfg: Config, args) -> int:
    from .license import make_key, verify_key
    if args.generate:
        key = make_key(args.generate, args.months, cfg.license_secret)
        print(key)
        return 0
    ok, status = check_license(cfg)
    print(json.dumps(status, indent=2))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="ATLAS autonomous trading agent")
    parser.add_argument("--env", default=None, help="path to .env file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run the autonomous loop")
    p_run.set_defaults(func=cmd_run)

    p_once = sub.add_parser("once", help="run a single cycle")
    p_once.set_defaults(func=cmd_once)

    p_bt = sub.add_parser("backtest", help="backtest the strategy on historical candles")
    p_bt.add_argument("symbol", nargs="?", default="BTC/USDT")
    p_bt.add_argument("--days", type=int, default=60)
    p_bt.add_argument("--source", choices=["live", "synth"], default="live")
    p_bt.set_defaults(func=cmd_backtest)

    p_st = sub.add_parser("status", help="portfolio and risk status")
    p_st.set_defaults(func=cmd_status)

    p_hist = sub.add_parser("history", help="trade/decision journal")
    p_hist.add_argument("kind", nargs="?", choices=["trades", "decisions", "all"], default="all")
    p_hist.add_argument("--limit", type=int, default=50)
    p_hist.set_defaults(func=cmd_history)

    p_eq = sub.add_parser("equity", help="equity curve rows")
    p_eq.add_argument("--limit", type=int, default=200)
    p_eq.set_defaults(func=cmd_equity)

    p_stats = sub.add_parser("stats", help="journal analytics: win rate by conviction/side/reason")
    p_stats.set_defaults(func=cmd_stats)

    p_kill = sub.add_parser("kill", help="engage or clear the kill switch")
    p_kill.add_argument("--off", action="store_true", help="clear the kill switch")
    p_kill.set_defaults(func=cmd_kill)

    p_license = sub.add_parser("license", help="generate or check subscription keys")
    p_license.add_argument("--generate", metavar="CUSTOMER", help="generate a key for a customer")
    p_license.add_argument("--months", type=int, default=1)
    p_license.set_defaults(func=cmd_license)

    p_reset = sub.add_parser("reset", help="reset paper state, journal and db")
    p_reset.add_argument("--yes", action="store_true")
    p_reset.set_defaults(func=cmd_reset)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "env", None):
        from dotenv import load_dotenv
        load_dotenv(args.env, override=True)
    cfg = Config.from_env()
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())