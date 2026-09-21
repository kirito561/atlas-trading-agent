# ATLAS — Autonomous Trading Logic & Analysis System

ATLAS is an autonomous crypto trading agent for **Bybit**. It scans markets,
builds multi-factor trade theses, sizes positions under hard risk limits,
executes (paper or live), journals every decision, and runs 24/7 with **no
human interaction**. It ships with a web dashboard and an HMAC-signed
**monthly subscription key** system so it can be licensed to customers.

> **Provenance of this build:** this repository was assembled from a short
> prompt that sketched a "non-negotiable rule set" for a trading agent. That
> review is reproduced below as **Product requirements**, and every safety
> rule it demanded is implemented in *code*, not in prose.

```
other/
├─ engine/        Python trading engine (analysis, risk, brokers, loop, CLI)
├─ dashboard/     Node/Express dashboard + license API
├─ tests/         unit tests (unittest, no external test runner)
├─ Dockerfile     single-container deployment
└─ .env.example   all configuration knobs
```

---

## Product requirements (from the review, and how they are enforced)

| Review point | Where it lives in code (not the prompt) |
|---|---|
| Rules must be enforced, never "recommended" | `engine/risk/manager.py` `RiskManager` sits between analysis and `broker.open_position(...)` and **rejects violating orders**. Sizing never exceeds risk budget, position cap, cash reserve, or daily/drawdown halts. |
| Peak equity & drawdown computed by code | `RiskManager.run_cycle_hooks` → `peak_equity`, `drawdown()`, `_check_drawdown`, `_check_daily_loss`. |
| Prompt injection via signal feeds (Telegram/Discord/Reddit/X) | ATLAS has no instruction channel and no LLM in the loop. The only external text input is optional news RSS sentiment, which is treated as **untrusted data**: it can nudge the score by a bounded amount only and can never change risk limits, operating modes, or emit instructions (`apply_sentiment`, capped ±~1 score point). The agent cannot raise its own limits or switch modes based on anything it reads. |
| Internal contradictions (8% cap vs 2% risk; defensive widening stops; cash reserve vs aggressive; long-term holds vs stops; undefined confidence trigger) | All resolved deterministically — see [Risk rules](#risk-rules-non-negotiable-enforced-in-code). Stops are bounded to 0.3–15%; because the position cap also binds, widening a stop can never push effective risk past the budget. Modes scale only the **position cap**, never the per-trade risk budget or the cash reserve. There are no "long-term hold" exemptions: every position has a stop and halt closes everything. No LLM confidence anywhere — mode triggers are measurable drawdown/day-loss thresholds. |
| Quantitative mode switching | `operate_mode()` in the risk manager uses only numbers: drawdown ≥ 3% **or** day-loss ≥ 1.5% ⇒ `defensive`; drawdown ≥ 10% ⇒ `halt`; optional `aggressive` only when drawdown < 1% and day P&L ≥ 0. Every transition is logged + notified. |
| Fees, slippage, liquidity, spread limits | `ATLAS_FEE_RATE` + `ATLAS_SLIPPAGE` model execution cost (paper). `ATLAS_MAX_SPREAD_PCT` and `ATLAS_MIN_VOLUME_24H` reject entries on illiquid/wide markets (`validate_ticker` runs immediately before the order). |
| Failure handling (API errors, stale data, timeouts, duplicates, kill switch) | Retry+backoff on Bybit data; stale-candle guard skips a symbol if its last candle is older than `timeframe × ATLAS_STALE_DATA_MULTIPLIER`; duplicate-entry guard (one position per symbol); retries around every fetch/close; `python -m engine kill` drop/kill file halts+closes positions on the next cycle and is the physical kill switch. |
| Market hours & asset-specific rules, short/margin policy | Crypto is 24/7; `ATLAS_ALLOW_SHORT` gates shorts; `ATLAS_MAX_LEVERAGE=1` is enforced per entry in live mode via `set_leverage` before every order; watchlist is the explicit asset allow-list. |
| Persistent state | ATLAS has **no memory between cycles**. Every cycle reloads `data/state.json`, `data/positions.json` and the SQLite journal, so a crash/restart resumes exactly. The dashboard reads only from the journal. |
| Compliance specifics | Jurisdiction risk is documented in [Legal & risk disclosure](#legal--risk-disclosure-read-this); the lightest path is licensing software the customer runs with their own exchange keys. |
| Tool schemas instead of prose | This README (API surface, function signatures) + `engine/cli.py` `argparse` are the tool contract. See [Function & API surface](#function--api-surface). |
| Conviction must be tested, not believed | Every score and outcome is journaled; `python -m engine stats` computes win rate by conviction band / side / exit reason. Verify an edge exists before trusting it. |
| Cheap wake-up, not LLM polling | The loop is rule-based indicator math (no LLM per cycle), so the cost per cycle is trivial; sentiment (the only network call per scan) is optional and cached 30 min. |

---

## Quickstart (paper trading)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env          # defaults are safe for paper trading

# one analysis + trading cycle against real Bybit market data
.\.venv\Scripts\python.exe -m engine once

# run the autonomous 24/7 loop (interval from ATLAS_INTERVAL_MINUTES)
.\.venv\Scripts\python.exe -m engine run

# portfolio / risk status, the trade journal, and win-rate analytics
.\.venv\Scripts\python.exe -m engine status
.\.venv\Scripts\python.exe -m engine history
.\.venv\Scripts\python.exe -m engine stats
.\.venv\Scripts\python.exe -m engine equity --limit 50

# emergency stop / resume (closes positions + halts on next cycle)
.\.venv\Scripts\python.exe -m engine kill
.\.venv\Scripts\python.exe -m engine kill --off

# backtest against real history (fallback: --source synth)
.\.venv\Scripts\python.exe -m engine backtest BTC/USDT --days 60

# reset paper account, journal and database
.\.venv\Scripts\python.exe -m engine reset --yes
```

### Dashboard

```powershell
cd dashboard
npm install
npm start            # http://localhost:4173
```

Try it interactively: `python -m engine run` in one terminal, `npm start` in
another, then open the dashboard — it auto-refreshes every 30s.

---

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ATLAS_MODE` | `paper` | `paper` or `live`. **Paper** uses a simulated account fed by real Bybit prices. **Live** requires Bybit API keys and trades real funds. |
| `ATLAS_START_BALANCE` | `1000` | Starting paper balance in `ATLAS_QUOTE` (USDT) |
| `ATLAS_INTERVAL_MINUTES` | `10` | Autonomous loop cycle interval |
| `ATLAS_WATCHLIST` | BTC,ETH,SOL | Symbols scanned each cycle (comma separated) |
| `ATLAS_TREND_TIMEFRAME` | `1h` | Analysis candle timeframe |
| `ATLAS_MIN_CONVICTION` | `7` | Conviction (1-10) required to enter |
| `ATLAS_RISK_PER_TRADE` | `0.02` | Max 2% of equity risked per trade (never exceeded by any mode) |
| `ATLAS_MAX_POSITION_PCT` | `0.08` | Max 8% of equity in a single position (scaled by mode factor) |
| `ATLAS_MAX_POSITIONS` | `4` | Max concurrent positions |
| `ATLAS_STOP_PCT` | `0.03` | Fallback stop distance if ATR is unavailable |
| `ATLAS_TAKE_PROFIT_RR` | `1.5` | Take-profit = risk:reward multiplier |
| `ATLAS_DRAWDOWN_HALT` | `0.10` | 10% portfolio drawdown -> full halt + close positions |
| `ATLAS_DAILY_LOSS_LIMIT` | `0.03` | 3% realized loss in a day -> halt until next day |
| `ATLAS_CASH_RESERVE` | `0.20` | Hard floor: 20%+ of equity stays in cash (no mode can touch it) |
| `ATLAS_COOLDOWN_MINUTES` | `30` | Lockout after a losing trade |
| `ATLAS_ALLOW_SHORT` | `false` | Enable short signals (paper/perp) |
| `ATLAS_FEE_RATE` / `ATLAS_SLIPPAGE` | `0.001` / `0.0005` | Simulated execution cost applied to paper fills |
| `ATLAS_MAX_SPREAD_PCT` | `1.0` | Reject entry if bid/ask spread > 1% of last price |
| `ATLAS_MIN_VOLUME_24H` | `0` | Skip symbols with 24h quote volume below this (liquidity gate) |
| `ATLAS_MAX_LEVERAGE` | `1` | Margin cap; enforced per live entry (spot = n/a) |
| `ATLAS_STALE_DATA_MULTIPLIER` | `3` | Skip a symbol if its last candle is > timeframe × this old |
| `ATLAS_ESCALATE_LOSS_PCT` | `0.015` | CRITICAL alert when one losing trade costs >1.5% of equity |
| `ATLAS_AGGRESSIVE_ENABLED` | `false` | Allow `aggressive` mode (scales position cap ×1.2, still ≤ risk budget) |
| `ATLAS_DEFENSIVE_DRAWDOWN` | `0.03` | Drawdown threshold that switches mode to `defensive` |
| `ATLAS_DAY_LOSS_DEFENSIVE` | `0.015` | Same-day realized loss that switches mode to `defensive` |
| `ATLAS_DEFENSIVE_MIN_CONVICTION` | `8` | Conviction floor during defensive mode |
| `ATLAS_AGGRESSIVE_SIZE_FACTOR` | `1.2` | Position-cap multiplier in aggressive mode |
| `ATLAS_DEFENSIVE_SIZE_FACTOR` | `0.6` | Position-cap multiplier in defensive mode |
| `BYBIT_API_KEY/SECRET` | — | Only used in `ATLAS_MODE=live` |
| `BYBIT_TESTNET` | `false` | Use Bybit testnet for live mode |
| `ATLAS_SENTIMENT_ENABLED` | `false` | Naive Google-News RSS sentiment (untrusted, bounded, off by default) |
| `ATLAS_NOTIFY_TELEGRAM_*` | — | Optional operator alerts via Telegram |
| `ATLAS_LICENSE_SECRET` | `change-me-please` | Secret that signs subscription keys |
| `ATLAS_LICENSE_REQUIRED` | `false` | Set `true` to refuse trading on an expired key |

---

## How the agent works

1. **Scan** — every cycle fetches `trend_timeframe` candles for the watchlist.
   Symbols with stale data (last candle older than `timeframe ×
   ATLAS_STALE_DATA_MULTIPLIER`) are skipped.
2. **Analyze** — EMA trend (20/50/200), MACD, RSI, Bollinger, VWAP, ADX,
   breakouts, volume spikes; optional news sentiment. Each signal votes long
   or short with a weight. Sentiment is untrusted, bounded data — it can
   never override limits or issue instructions.
3. **Score** — a net score in roughly `[-6, +6]` maps to a **conviction 1-10**.
   No trade below `ATLAS_MIN_CONVICTION` (raised to `ATLAS_DEFENSIVE_MIN_CONVICTION`
   in defensive mode); shorts require `ATLAS_ALLOW_SHORT`.
4. **Size** — position is risk-capped: `equity × risk_per_trade ÷ stop
   distance`, then clamped by the position cap (scaled by the operating mode)
   and the cash reserve. The resulting effective risk
   (size × entry × stop distance) is re-checked against the
   `equity × risk_per_trade` budget before the order is allowed to open.
5. **Execute** — the live ticker is validated (spread ≤ `ATLAS_MAX_SPREAD_PCT`,
   volume ≥ `ATLAS_MIN_VOLUME_24H`) *immediately before* the order; then a
   market order with simulated slippage + fees (paper) or a real Bybit perp
   order with attached stop-loss/take-profit and enforced leverage (live).
6. **Manage** — each cycle checks stop / take-profit / time exit, and trails
   the stop once the position is in profit. A single losing trade that costs
   more than `ATLAS_ESCALATE_LOSS_PCT` of equity fires a CRITICAL operator alert.
7. **Review** — every decision and trade is written to the SQLite journal
   (`data/atlas.db`); equity snapshots feed the dashboard curve. Use
   `python -m engine stats` to test whether conviction actually predicts
   outcomes before trusting it.

The agent has **zero memory between cycles** — positions, state and the
journal all reload from `data/` on every tick, so it restarts cleanly after
any crash or redeploy. A physical kill switch (`data/kill`, written by
`python -m engine kill`) forces a full close+halt and is the deterministic
stop override for a running session.

### Progression tables for conviction

| Score | Conviction | Action |
|---|---|---|
| < 0.5 | 1-5 | hold / skip |
| 0.8-1.2 | 6 | watchlist |
| 1.2-1.8 | 7 | small position |
| 1.8-2.3 | 8 | standard position |
| 2.3-3.0 | 9 | aggressive |
| ≥ 3.0 | 10 | highest conviction (still ≤ 8% position cap) |

---

## Risk rules (non-negotiable, enforced in code)

- Max **2%** of equity risked per trade (entry-to-stop distance × size).
  This budget is **never exceeded**, in any operating mode.
- Max **8%** of equity in any single position (scaled by mode: ×1.2
  aggressive, ×0.6 defensive).
- **Stop-loss on every position** — no exemptions, no "long-term holds".
- **10% drawdown** from peak ⇒ full halt, positions closed, cash held.
- **3% same-day realized loss** ⇒ trading halts until the next UTC day.
- **>20% must stay in cash** (`ATLAS_CASH_RESERVE`) — a hard floor no mode can
  touch (aggressive mode grows exposure only within the remaining envelope).
- Losing trade ⇒ **30 min cooldown** before the next entry.
- Collective exposure against a 50% portfolio cap.
- Stops are bounded to **0.3%–15%** from entry.

> **Why the 2%-vs-8% contradiction resolves itself:** the position cap is a
> second, tighter budget. With an 8% cap, effective risk = 8% × stop width.
> Even at the widest allowed stop (15%) that is 1.2% — under the 2% budget.
> So *widening* a stop (e.g. via ATR in defensive regimes) can never break the
> 2% rule: the cap absorbs it. Aggressive mode raises the cap, not the budget,
> and the final effective-risk re-check in `size_position` closes the loop.

### Operating modes (all thresholds measurable, no LLM confidence)

| Mode | Trigger | Effect |
|---|---|---|
| `normal` | default | cap ×1.0, conviction floor = `ATLAS_MIN_CONVICTION` |
| `defensive` | drawdown ≥ `ATLAS_DEFENSIVE_DRAWDOWN` (3%) **or** same-day loss ≥ `ATLAS_DAY_LOSS_DEFENSIVE` (1.5%) | cap × `ATLAS_DEFENSIVE_SIZE_FACTOR` (0.6), conviction floor = `ATLAS_DEFENSIVE_MIN_CONVICTION` (8) |
| `aggressive` | only if `ATLAS_AGGRESSIVE_ENABLED=true`, drawdown < 1% **and** day P&L ≥ 0 | cap × `ATLAS_AGGRESSIVE_SIZE_FACTOR` (1.2), still never above the 2% risk budget |
| `halt` | drawdown ≥ `ATLAS_DRAWDOWN_HALT` (10%) or daily-loss limit or kill switch | no entries; all positions closed |

Every transition is notified (INFO/WARNING/CRITICAL) and recorded in the
journal.

---

## Backtesting

```powershell
.\.venv\Scripts\python.exe -m engine backtest ETH/USDT --days 90 --source live
.\.venv\Scripts\python.exe -m engine backtest SOL/USDT --days 30 --source synth
```

Reports trades, win rate, average R:R, profit factor, max drawdown, total
return and a Sharpe estimate. The same engine code drives both live
execution and backtests, so a strategy that works in backtest is what you
get in paper/live. Backtests run in an isolated temp directory: they cannot
pollute the live journal, positions or state.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

In addition to the mechanics, use `python -m engine stats` on the live paper
journal to answer the only question that matters: **does a higher conviction
score actually produce a higher win rate?** If not, the conviction bands are
noise and no amount of automation will fix that — tune the signal weights in
`engine/analysis/technical.py` and re-backtest.

---

## Readiness checklist (paper → live)

1. **Backtest** BTC/ETH/SOL for 60–90 days across both bull and bear regimes.
   Reject the system if any period shows a large drawdown near the 10% halt.
2. **Paper trade 2–4 weeks** with `ATLAS_MODE=paper` and `--env` untouched.
   Watch `python -m engine stats`: win rate by conviction band and by exit
   reason. Duplicate entries? Then the risk gates are too loose.
3. **Stress the failure paths**: `python -m engine kill` (must close+halt),
   kill the process mid-cycle and restart (state resumes), run with a fake
   stale candle (symbol skipped).
4. **Go live small** — testnet first (`BYBIT_TESTNET=true`), then a tiny
   `ATLAS_START_BALANCE` live wallet. Keep the same risk settings for at
   least a week before touching any knob.
5. Only after a profitable month live do you raise `ATLAS_MAX_POSITION_PCT`
   or enable `ATLAS_AGGRESSIVE_ENABLED` — and re-run the checklist each time.

---

## Live trading

1. Create a Bybit API key (spot/perp permission, IP-allowlist it, **no**
   withdrawal permission). Note: Bybit does not serve US persons; check your
   local exchange availability before real funds.
2. Set `ATLAS_MODE=live`, `BYBIT_API_KEY`, `BYBIT_API_SECRET`. Use
   `BYBIT_TESTNET=true` first.
3. Start with the same limits: `run` refuses to start with an expired
   license and will not open a position that breaks any risk rule.

ATLAS executes market orders with attached stop-loss/take-profit and enforces
`ATLAS_MAX_LEVERAGE` per entry. Start small, watch the journal closely, and
validate against paper results.

---

## Function & API surface

The tool contract (the "schemas" the agent and the dashboard call):

```
engine/risk/manager.py
  RiskManager.operate_mode() -> "normal" | "defensive" | "aggressive" | "halt"
  RiskManager.min_conviction_floor() -> int
  RiskManager.can_trade() -> (bool, reason)
  RiskManager.can_open_more() -> (bool, reason)
  RiskManager.size_position(analysis: Analysis) -> dict  # qty/entry/stop/target
  RiskManager.record_trade_result(pnl: float) -> None
  RiskManager.clear_halt() -> None
engine/guards.py
  candles_stale(candles: list[Candle], cfg: Config, tf: str) -> bool
  validate_ticker(t: Ticker, cfg: Config) -> (bool, reason)
engine/broker/base.py (interface implemented by PaperBroker / BybitLiveBroker)
  fetch_candles(symbol, timeframe, limit) -> list[Candle]
  fetch_ticker(symbol) -> Ticker
  open_position(symbol, side, qty, price, stop, target, conviction, reason) -> Position
  close_position(position, price, reason) -> ClosedTrade
  update_position(position, *, stop, target) -> Position
  mark_to_market() -> float
  get_balance() -> dict
engine/memory/storage.py Store
  record_trade / record_decision / record_equity / snapshot_positions / win_stats
CLI (python -m engine <cmd>)
  run | once | backtest <SYM> | status | history | equity | stats | kill [--off] | license | reset
Dashboard HTTP API
  GET /api/status | /api/trades | /api/equity | /api/decisions | /api/license
  POST /api/license/generate | /api/license/renew   (header: x-admin-token)
```

All typed parameters as above; nothing in ATLAS consumes a free-form prompt
at runtime, so there is no surface for instruction injection.

---

## Subscription licensing (the product layer)

Keys are HMAC-SHA256 signed and carry an expiry — so a 1-month key stops
working 1 month after issue. Sign and verify are implemented **identically**
in Python (engine) and Node (dashboard).

```powershell
# generate a 1-month key for a customer (Python)
.\.venv\Scripts\python.exe -m engine license --generate acme-trader --months 1
ATLAS.eyJjdXN0b21lciI6ImFjbWUtdHJhZGVyIi...

# check the configured key
.\.venv\Scripts\python.exe -m engine license
```

For the engine to actually refuse trading on expiry:

```
ATLAS_LICENSE_REQUIRED=true
# write the customer key to data/license.key (or ATLAS_LICENSE_KEY)
```

From the dashboard (admin panel → License tab) you can generate, verify and
renew keys. To wire up monthly billing, point your payment processor
(Stripe/Paddle/Coinbase Commerce) webhook at a small endpoint that calls the
same `generateKey(customer, 1, secret)` and writes the key to `data/license.key`.

```
POST /api/license/generate   {customer, months}   (header: x-admin-token)
POST /api/license/renew      {key, months}        (header: x-admin-token)
GET  /api/license/verify?key=...
```

---

## Deployment

A single Dockerfile runs the engine (foreground) and the dashboard
(background):

```powershell
docker build -t atlas .
docker run -d --name atlas -p 4173:4173 `
  -v ${PWD}/data:/app/data -v ${PWD}/.env:/app/.env atlas
```

Point a reverse proxy (Caddy/nginx) at port 4173. For a real product you
want: the `.env` with `ATLAS_LICENSE_REQUIRED=true`, a real
`ATLAS_LICENSE_SECRET`, an admin token, and a monitored VPS (the journal is
your audit trail).

---

## Legal & risk disclosure (read this)

- **No software guarantees returns.** ATLAS is capital-preservation-first by
  design, but all trading involves risk of total loss. Backtests and paper
  results are not indicative of future performance.
- ATLAS is a **tool**: robots do not get FOMO, but they also cannot predict
  flash crashes, exchange outages, or geopolitical shocks. The 10%
  drawdown halt is your last line of defense — keep it.
- **If you sell subscriptions** in which the software trades other people's
  money, most jurisdictions classify that as an investment or trading
  service requiring authorisation (e.g. SEC/FCA/SEBI equivalents). Selling
  the software as a license that the buyer runs with **their own keys** is a
  different (usually lighter) regulatory profile. Verify with a local lawyer
  before charging anyone.
- **Automated-trading rules differ by country and broker.** Bybit does not
  serve US persons; the EU (MiCA), UK (FCA), India, China and others each
  restrict algo-trading / crypto differently. ATLAS ships no
  jurisdiction-specific compliance logic on purpose — the operator is
  responsible for their own market access. Keep `ATLAS_WATCHLIST` to assets
  your jurisdiction permits, and keep position sizing small.
- Only trade with money you can afford to lose. Start in paper mode. The
  journal (`data/atlas.db`) is the audit trail regulators expect: every
  entry, sizing decision, and exit reason is recorded with a timestamp.