from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from ..config import Config
from ..models import ClosedTrade, Position

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry REAL NOT NULL,
    exit REAL NOT NULL,
    pnl REAL NOT NULL,
    pnl_pct REAL NOT NULL,
    reason TEXT NOT NULL,
    conviction INTEGER NOT NULL,
    opened_at INTEGER NOT NULL,
    closed_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    conviction INTEGER NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    operating_mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_closed ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity(ts);
"""


class Store:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.db_path: Path = cfg.db_file
        self._lock = threading.RLock()
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def record_trade(self, trade: ClosedTrade) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (trade.id, trade.symbol, trade.side.value, trade.qty, trade.entry,
                     trade.exit, trade.pnl, trade.pnl_pct, trade.reason.value,
                     trade.conviction, trade.opened_at, trade.closed_at),
                )
                conn.commit()
            finally:
                conn.close()

    def record_decision(self, symbol: str, action: str, conviction: int, details: dict) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO decisions (ts, symbol, action, conviction, details) VALUES (?,?,?,?,?)",
                    (int(time.time()), symbol, action, conviction, json.dumps(details)),
                )
                conn.commit()
            finally:
                conn.close()

    def record_equity(self, equity: float, cash: float, operating_mode: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO equity (ts, equity, cash, operating_mode) VALUES (?,?,?,?)",
                    (int(time.time()), equity, cash, operating_mode),
                )
                conn.commit()
            finally:
                conn.close()

    def snapshot_positions(self, positions: list[Position]) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("INSERT INTO positions (ts, data) VALUES (?,?)",
                             (int(time.time()), json.dumps([p.to_dict() for p in positions])))
                conn.commit()
            finally:
                conn.close()

    def recent_trades(self, limit: int = 100) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def recent_decisions(self, limit: int = 100) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM decisions ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
                rows = [dict(r) for r in rows]
                for r in rows:
                    r["details"] = json.loads(r["details"])
                return rows
            finally:
                conn.close()

    def equity_history(self, limit: int = 2000) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM equity ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in reversed(rows)]
            finally:
                conn.close()

    def summary(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                win = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE pnl > 0"
                ).fetchone()[0]
                total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                pnl = conn.execute("SELECT COALESCE(SUM(pnl),0) FROM trades").fetchone()[0]
                return {"trades": total, "wins": win, "losses": total - win, "net_pnl": pnl}
            finally:
                conn.close()

    def win_stats(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                groups = {
                    "by_conviction": """
                        SELECT conviction,
                               COUNT(*) AS n,
                               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                               ROUND(AVG(pnl), 4) AS avg_pnl
                        FROM trades GROUP BY conviction ORDER BY conviction
                    """,
                    "by_side": """
                        SELECT side,
                               COUNT(*) AS n,
                               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                               ROUND(AVG(pnl), 4) AS avg_pnl
                        FROM trades GROUP BY side ORDER BY side
                    """,
                    "by_reason": """
                        SELECT reason,
                               COUNT(*) AS n,
                               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                               ROUND(AVG(pnl), 4) AS avg_pnl
                        FROM trades GROUP BY reason ORDER BY n DESC
                    """,
                }
                out = {}
                total = 0
                wins = 0
                for name, query in groups.items():
                    rows = conn.execute(query).fetchall()
                    rows = [dict(r) for r in rows]
                    for r in rows:
                        r["win_rate"] = round(r["wins"] / r["n"], 4) if r["n"] else 0.0
                    out[name] = rows
                    if name == "by_side":
                        for r in rows:
                            total += r["n"]
                            wins += r["wins"]
                out["overall"] = {
                    "trades": total,
                    "win_rate": round(wins / total, 4) if total else 0.0,
                }
                return out
            finally:
                conn.close()