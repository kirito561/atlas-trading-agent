from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = PROJECT_ROOT / ".env"
if DEFAULT_ENV.exists():
    load_dotenv(DEFAULT_ENV)
else:
    load_dotenv()


def _get(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    val = _get(name, "").lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = _get(name, "")
    if not raw:
        return default
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    mode: str = "paper"
    start_balance: float = 1000.0
    quote: str = "USDT"
    interval_minutes: int = 10
    trend_timeframe: str = "1h"
    entry_timeframe: str = "15m"
    backtest_timeframe: str = "1h"
    watchlist: list[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    risk_per_trade: float = 0.02
    max_position_pct: float = 0.08
    max_positions: int = 4
    correlated_exposure_cap: float = 0.20
    stop_pct: float = 0.03
    take_profit_rr: float = 1.5
    trail_stop: bool = True
    trail_pct: float = 0.02
    drawdown_halt: float = 0.10
    daily_loss_limit: float = 0.03
    cash_reserve: float = 0.20
    cooldown_minutes: int = 30
    funding_rate: float = 0.0001
    allow_short: bool = False
    max_hold_bars: int = 96
    min_conviction: int = 7
    sentiment_enabled: bool = False
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = False
    notify_telegram_bot_token: str = ""
    notify_telegram_chat_id: str = ""
    license_secret: str = "change-me-please"
    admin_token: str = "change-me-please"
    dashboard_port: int = 4173
    license_key: str = ""
    license_required: bool = False
    fee_rate: float = 0.001
    slippage: float = 0.0005
    max_spread_pct: float = 1.0
    min_volume_24h: float = 0.0
    max_leverage: int = 1
    stale_data_multiplier: int = 3
    check_stale: bool = True
    escalate_loss_pct: float = 0.015
    aggressive_enabled: bool = False
    defensive_drawdown_threshold: float = 0.03
    day_loss_defensive_threshold: float = 0.015
    defensive_min_conviction: int = 8
    aggressive_size_factor: float = 1.2
    defensive_size_factor: float = 0.6
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls(
            mode=_get("ATLAS_MODE", "paper").lower(),
            start_balance=_get_float("ATLAS_START_BALANCE", 1000.0),
            quote=_get("ATLAS_QUOTE", "USDT").upper(),
            interval_minutes=_get_int("ATLAS_INTERVAL_MINUTES", 10),
            trend_timeframe=_get("ATLAS_TREND_TIMEFRAME", "1h"),
            entry_timeframe=_get("ATLAS_ENTRY_TIMEFRAME", "15m"),
            backtest_timeframe=_get("ATLAS_BACKTEST_TIMEFRAME", "1h"),
            watchlist=_get_list("ATLAS_WATCHLIST", ["BTC/USDT", "ETH/USDT", "SOL/USDT"]),
            risk_per_trade=_get_float("ATLAS_RISK_PER_TRADE", 0.02),
            max_position_pct=_get_float("ATLAS_MAX_POSITION_PCT", 0.08),
            max_positions=_get_int("ATLAS_MAX_POSITIONS", 4),
            correlated_exposure_cap=_get_float("ATLAS_CORRELATED_EXPOSURE_CAP", 0.20),
            stop_pct=_get_float("ATLAS_STOP_PCT", 0.03),
            take_profit_rr=_get_float("ATLAS_TAKE_PROFIT_RR", 1.5),
            trail_stop=_get_bool("ATLAS_TRAIL_STOP", True),
            trail_pct=_get_float("ATLAS_TRAIL_PCT", 0.02),
            drawdown_halt=_get_float("ATLAS_DRAWDOWN_HALT", 0.10),
            daily_loss_limit=_get_float("ATLAS_DAILY_LOSS_LIMIT", 0.03),
            cash_reserve=_get_float("ATLAS_CASH_RESERVE", 0.20),
            cooldown_minutes=_get_int("ATLAS_COOLDOWN_MINUTES", 30),
            funding_rate=_get_float("ATLAS_FUNDING_RATE", 0.0001),
            allow_short=_get_bool("ATLAS_ALLOW_SHORT", False),
            max_hold_bars=_get_int("ATLAS_MAX_HOLD_BARS", 96),
            min_conviction=_get_int("ATLAS_MIN_CONVICTION", 7),
            sentiment_enabled=_get_bool("ATLAS_SENTIMENT_ENABLED", False),
            bybit_api_key=_get("BYBIT_API_KEY"),
            bybit_api_secret=_get("BYBIT_API_SECRET"),
            bybit_testnet=_get_bool("BYBIT_TESTNET", False),
            notify_telegram_bot_token=_get("ATLAS_NOTIFY_TELEGRAM_BOT_TOKEN"),
            notify_telegram_chat_id=_get("ATLAS_NOTIFY_TELEGRAM_CHAT_ID"),
            license_secret=_get("ATLAS_LICENSE_SECRET", "change-me-please"),
            admin_token=_get("ATLAS_ADMIN_TOKEN", "change-me-please"),
            dashboard_port=_get_int("DASHBOARD_PORT", 4173),
            license_key=_get("ATLAS_LICENSE_KEY"),
            license_required=_get_bool("ATLAS_LICENSE_REQUIRED", False),
            fee_rate=_get_float("ATLAS_FEE_RATE", 0.001),
            slippage=_get_float("ATLAS_SLIPPAGE", 0.0005),
            max_spread_pct=_get_float("ATLAS_MAX_SPREAD_PCT", 1.0),
            min_volume_24h=_get_float("ATLAS_MIN_VOLUME_24H", 0.0),
            max_leverage=_get_int("ATLAS_MAX_LEVERAGE", 1),
            stale_data_multiplier=_get_int("ATLAS_STALE_DATA_MULTIPLIER", 3),
            check_stale=_get_bool("ATLAS_CHECK_STALE", True),
            escalate_loss_pct=_get_float("ATLAS_ESCALATE_LOSS_PCT", 0.015),
            aggressive_enabled=_get_bool("ATLAS_AGGRESSIVE_ENABLED", False),
            defensive_drawdown_threshold=_get_float("ATLAS_DEFENSIVE_DRAWDOWN", 0.03),
            day_loss_defensive_threshold=_get_float("ATLAS_DAY_LOSS_DEFENSIVE", 0.015),
            defensive_min_conviction=_get_int("ATLAS_DEFENSIVE_MIN_CONVICTION", 8),
            aggressive_size_factor=_get_float("ATLAS_AGGRESSIVE_SIZE_FACTOR", 1.2),
            defensive_size_factor=_get_float("ATLAS_DEFENSIVE_SIZE_FACTOR", 0.6),
        )
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        if not cfg.license_key:
            key_file = cfg.data_dir / "license.key"
            if key_file.exists():
                cfg.license_key = key_file.read_text(encoding="utf-8").strip()
        return cfg

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "atlas.db"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "atlas.lock"

    @property
    def positions_file(self) -> Path:
        return self.data_dir / "positions.json"

    @property
    def kill_switch_file(self) -> Path:
        return self.data_dir / "kill"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        d["data_dir"] = str(self.data_dir)
        return d


def load_state(cfg: Config) -> dict:
    if cfg.state_file.exists():
        try:
            return json.loads(cfg.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(cfg: Config, state: dict) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg.state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(cfg.state_file)