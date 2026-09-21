const $ = (sel) => document.querySelector(sel)
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))

const fmt = (v, d = 2) => {
  if (v === undefined || v === null || Number.isNaN(Number(v))) return "—"
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: d })
}
const fmtSigned = (v, d = 2) => {
  if (v === undefined || v === null || Number.isNaN(Number(v))) return "—"
  const n = Number(v)
  return (n > 0 ? "+" : "") + n.toLocaleString("en-US", { maximumFractionDigits: d })
}
const fmtPct = (v) => (v === undefined || v === null ? "—" : fmt(v, 2) + "%")
const fmtSignedPct = (v) => (v === undefined || v === null ? "—" : fmtSigned(v, 2) + "%")
const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "—")
const fmtDate = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString() : "—")

const REFRESH_MS = 30000
let nextRefresh = 0

document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.remove("active"))
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"))
    btn.classList.add("active")
    $("#view-" + btn.dataset.view).classList.add("active")
  })
})

async function json(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(url + " -> " + res.status)
  return res.json()
}

$("#refreshBtn").addEventListener("click", () => {
  $("#refreshBtn").classList.add("spin")
  refreshAll(true).finally(() => $("#refreshBtn").classList.remove("spin"))
})

function card(k, v, cls, sub) {
  const t = $("#cardTmpl").content.cloneNode(true)
  t.querySelector(".k").textContent = k
  const val = t.querySelector(".v")
  val.textContent = v
  if (cls) val.classList.add(cls)
  if (sub) {
    const s = document.createElement("div")
    s.className = "s"
    s.textContent = sub
    val.after(s)
  }
  return t
}

function renderModeChip(s) {
  const chip = $("#modeChip")
  const halted = s.halted
  const mode = halted ? "halt" : (s.operating_mode || "—")
  chip.textContent = "mode · " + mode
  chip.className = "chip " + (halted ? "down" : mode === "defensive" ? "warn" : mode === "aggressive" ? "up" : "normal" ? "up" : "")
}

function renderStatus(data) {
  const s = data.status || {}
  const cards = $("#cards")
  cards.innerHTML = ""
  const dd = s.drawdown ? s.drawdown * 100 : 0
  const ddCls = s.halted ? "down" : dd >= 3 ? "warn" : "up"
  const exposureCls = s.exposure_pct >= 50 ? "warn" : ""
  cards.appendChild(card("Equity", fmt(s.equity, 2) + " USDT", "info", "peak " + fmt(s.peak_equity, 2)))
  cards.appendChild(card("Cash", fmt(s.cash, 2) + " USDT", "", "reserve " + fmtPct(s.cash_reserve_pct)))
  cards.appendChild(card("Drawdown", fmtPct(dd), ddCls, "halt at 10%"))
  cards.appendChild(card("Exposure", fmtPct(s.exposure_pct), exposureCls, "of equity"))
  cards.appendChild(card("Day P&L", fmtSigned(s.day_pnl, 2), s.day_pnl >= 0 ? "up" : "down", "today"))
  cards.appendChild(card("Journal net", fmtSigned((data.journal || {}).net, 2), (data.journal || {}).net >= 0 ? "up" : "down", (data.journal || {}).total + " trades"))
  cards.appendChild(card("Open positions", String(s.open_positions || 0), "", "max " + (s.max_positions || "—")))
  cards.appendChild(card("Risk / trade", fmtPct(s.risk_per_trade_pct), "", "budget"))
  renderRiskBars(s)
  renderPositions(data.open_positions || [])
  renderModeChip(s)
}

function riskMeter(pct, threshold, max) {
  const p = Math.max(0, Math.min(1, pct / (max || 1)))
  const cls = pct >= threshold ? "bad" : pct >= threshold * 0.6 ? "mix" : "good"
  return `<div class="bar ${cls}"><i style="width:${(p * 100).toFixed(1)}%"></i></div>`
}

function renderRiskBars(s) {
  const el = $("#riskBars")
  const dd = s.drawdown ? s.drawdown * 100 : 0
  const dayLoss = s.day_pnl < 0 ? Math.abs(s.day_pnl) : 0
  const dayLimit = s.daily_loss_limit ? s.daily_loss_limit * 100 : 3
  const posMax = s.max_positions || 1
  el.innerHTML =
    `<div class="risk-row">
       <div class="rk"><b>Drawdown</b><span>${fmt(dd, 2)}% / ${fmt(dayLimit, 2)}% day limit</span></div>
       ${riskMeter(dd, dayLimit, s.daily_loss_limit ? dayLimit : 10)}
     </div>
     <div class="risk-row">
       <div class="rk"><b>Positions used</b><span>${s.open_positions || 0} / ${s.max_positions || "—"}</span></div>
       ${riskMeter(s.open_positions || 0, posMax, posMax)}
     </div>
     <div class="risk-row">
       <div class="rk"><b>Exposure</b><span>${fmt(s.exposure_pct, 2)}% of equity</span></div>
       <div class="bar info"><i style="width:${Math.min(100, s.exposure_pct || 0).toFixed(1)}%"></i></div>
     </div>
     <div class="risk-row">
       <div class="rk"><b>Cash reserve</b><span>${fmt(s.cash_reserve_pct, 2)}% (floor 20%)</span></div>
       <div class="bar info"><i style="width:${Math.min(100, s.cash_reserve_pct || 0).toFixed(1)}%"></i></div>
     </div>`
}

function renderPositions(positions) {
  const tbody = $("#positionsBody")
  tbody.innerHTML = ""
  $("#posCount").textContent = positions.length + " open"
  $("#positionsEmpty").style.display = positions.length ? "none" : "block"
  positions.forEach((p) => {
    const tr = document.createElement("tr")
    const up = p.unrealized_pnl >= 0
    tr.innerHTML =
      `<td><b>${esc(p.symbol)}</b></td>` +
      `<td><span class="badge ${p.side === "long" ? "long" : "short"}">${esc(p.side)}</span></td>` +
      `<td>${fmt(p.qty)}</td><td>${fmt(p.entry)}</td><td class="down">${fmt(p.stop)}</td><td class="up">${fmt(p.target)}</td>` +
      `<td>${fmt(p.last_price)}</td>` +
      `<td class="${up ? "up" : "down"}">${fmtSigned(p.unrealized_pnl)}</td>` +
      `<td class="${up ? "up" : "down"}">${fmtSignedPct(p.unrealized_pct)}</td>`
    tbody.appendChild(tr)
  })
}

function renderEquityChart(tryData) {
  const canvas = $("#equityChart")
  const ctx = canvas.getContext("2d")
  const dpr = window.devicePixelRatio || 1
  const W = canvas.clientWidth || 400
  const H = 260
  canvas.width = W * dpr
  canvas.height = H * dpr
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, W, H)
  const meta = $("#eqMeta")

  const rows = (tryData || []).slice().sort((a, b) => (a.ts || 0) - (b.ts || 0))
  if (rows.length < 2) {
    ctx.fillStyle = "#7d8db1"
    ctx.font = "13px ui-monospace, monospace"
    ctx.fillText("Not enough data yet — run: python -m engine once", 16, H / 2)
    meta.textContent = ""
    return
  }

  const values = rows.map((r) => Number(r.equity))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const padL = 46
  const padR = 14
  const padT = 18
  const padB = 26
  const iw = W - padL - padR
  const ih = H - padT - padB
  const x = (i) => padL + (i / (values.length - 1)) * iw
  const y = (v) => padT + ih - ((v - min) / span) * ih

  ctx.font = "11px ui-monospace, monospace"
  ctx.fillStyle = "#53627f"
  for (let g = 0; g <= 3; g++) {
    const v = min + (span * g) / 3
    const gy = y(v)
    ctx.strokeStyle = "rgba(28,42,68,.55)"
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(padL, gy)
    ctx.lineTo(W - padR, gy)
    ctx.stroke()
    ctx.fillText(fmt(v), 6, gy + 4)
  }

  ctx.strokeStyle = "rgba(56,189,248,.18)"
  ctx.beginPath()
  ctx.moveTo(padL, y(values[0]))
  values.forEach((v, i) => ctx.lineTo(x(i), y(v)))
  ctx.lineTo(x(values.length - 1), padT + ih)
  ctx.lineTo(padL, padT + ih)
  ctx.closePath()
  const grad = ctx.createLinearGradient(0, padT, 0, padT + ih)
  grad.addColorStop(0, "rgba(56,189,248,.28)")
  grad.addColorStop(1, "rgba(56,189,248,0)")
  ctx.fillStyle = grad
  ctx.fill()

  ctx.strokeStyle = "#38bdf8"
  ctx.lineWidth = 2
  ctx.lineJoin = "round"
  ctx.beginPath()
  values.forEach((v, i) => (i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v))))
  ctx.stroke()

  const last = values[values.length - 1]
  const tx = x(values.length - 1)
  ctx.fillStyle = "#38bdf8"
  ctx.beginPath()
  ctx.arc(tx, y(last), 3.5, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = "rgba(255,255,255,.85)"
  ctx.lineWidth = 1.5
  ctx.stroke()

  ctx.fillStyle = "#94a3b8"
  ctx.fillText(fmt(last), Math.min(tx + 10, W - 60), y(last) - 8)

  ctx.fillStyle = "#53627f"
  ctx.font = "10px ui-monospace, monospace"
  ctx.fillText(fmt(min), 6, padT + ih + 14)
  ctx.fillText(fmt(max), padL + iw - 40, padT + ih + 14)
  meta.textContent = "high " + fmt(max) + " · low " + fmt(min)

  const lastTs = rows[rows.length - 1].ts
  ctx.fillStyle = "#53627f"
  ctx.textAlign = "right"
  ctx.fillText(fmtDate(lastTs), W - padR, padT + ih + 14)
  ctx.textAlign = "left"
}

function sidelineTime(t) {
  return t.opened_at ? fmtTime(t.opened_at) : "—"
}

function computeStats(trades) {
  const wins = trades.filter((t) => t.pnl > 0)
  const losses = trades.filter((t) => t.pnl < 0)
  const winSum = wins.reduce((a, t) => a + t.pnl, 0)
  const lossSum = losses.reduce((a, t) => a + t.pnl, 0)
  const pf = lossSum === 0 ? (winSum > 0 ? 0 : 0) : winSum / Math.abs(lossSum)
  return {
    total: trades.length,
    wins: wins.length,
    losses: losses.length,
    winRate: trades.length ? wins.length / trades.length : 0,
    pf,
    avgWin: wins.length ? winSum / wins.length : 0,
    avgLoss: losses.length ? lossSum / losses.length : 0,
  }
}

function renderTradesStats(rows) {
  const st = computeStats(rows)
  const strip = $("#tradeStats")
  strip.innerHTML = ""
  const items = [
    ["Trades", String(st.total), ""],
    ["Win rate", st.total ? fmtPct(st.winRate * 100) : "—", st.winRate >= 0.5 ? "up" : st.winRate > 0 ? "warn" : "muted"],
    ["Wins / losses", st.wins + " / " + st.losses, ""],
    ["Profit factor", st.total ? fmt(st.pf, 2) : "—", st.pf >= 1 ? "up" : st.pf > 0 ? "warn" : ""],
    ["Avg win", fmtSigned(st.avgWin, 2), st.avgWin >= 0 ? "up" : ""],
    ["Avg loss", fmtSigned(st.avgLoss, 2), st.avgLoss < 0 ? "down" : ""],
  ]
  items.forEach(([k, v, cls]) => strip.appendChild(card(k, v, cls)))
}

function renderTrades(rows) {
  renderTradesStats(rows)
  const tbody = $("#tradesBody")
  tbody.innerHTML = ""
  rows.forEach((t) => {
    const tr = document.createElement("tr")
    const up = t.pnl >= 0
    tr.innerHTML =
      `<td>${fmtTime(t.closed_at || t.opened_at)}</td><td>${sidelineTime(t)}</td>` +
      `<td><b>${esc(t.symbol)}</b></td>` +
      `<td><span class="badge ${t.side === "long" ? "long" : "short"}">${esc(t.side)}</span></td>` +
      `<td>${fmt(t.qty)}</td><td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td>` +
      `<td class="${up ? "up" : "down"}">${fmtSigned(t.pnl, 2)}</td>` +
      `<td class="${up ? "up" : "down"}">${fmtSignedPct(t.pnl_pct)}</td>` +
      `<td><span class="badge reason">${esc(t.reason)}</span></td>` +
      `<td><span class="conv-bar"><i style="width:${((t.conviction || 0) * 10).toFixed(0)}%"></i></span> ${t.conviction || "—"}/10</td>`
    tbody.appendChild(tr)
  })
}

function renderDecisions(rows) {
  const tbody = $("#decisionsBody")
  tbody.innerHTML = ""
  rows.forEach((d) => {
    const tr = document.createElement("tr")
    let detail = "—"
    try {
      const obj = typeof d.details === "string" ? JSON.parse(d.details) : d.details
      detail = obj ? JSON.stringify(obj, null, 1) : "—"
    } catch {
      detail = esc(String(d.details ?? ""))
    }
    const actionCls = d.action === "enter" ? "up" : d.action === "exit" ? "warn" : d.action === "error" ? "down" : ""
    tr.innerHTML =
      `<td>${fmtTime(d.ts)}</td><td><b>${esc(d.symbol)}</b></td>` +
      `<td class="${actionCls}">${esc(d.action)}</td>` +
      `<td>${d.conviction || "—"}<span class="faint">/10</span></td>` +
      `<td class="detail"><pre>${esc(detail)}</pre></td>`
    tbody.appendChild(tr)
  })
}

function renderLicense(lic) {
  const box = $("#licenseStatus")
  const c = (lic && lic.check) || {}
  if (c.valid) {
    box.className = "license-box ok"
    box.textContent = "Active" + (lic.key ? " · " + lic.key : "") + " · expires " + c.data.expires + " · " + c.data.remaining_days + " days left"
  } else {
    box.className = "license-box bad"
    box.textContent = "No active license — " + (c.reason || "configure a key")
  }
}

$("#verifyBtn").addEventListener("click", async () => {
  const key = $("#verifyInput").value.trim()
  if (!key) return
  const el = $("#verifyResult")
  try {
    const r = await json("/api/license/verify?key=" + encodeURIComponent(key))
    const c = r.check || {}
    if (c.valid) {
      el.className = "result ok"
      el.textContent = `Valid for ${c.data.customer} · expires ${c.data.expires} · ${c.data.remaining_days} days remaining`
    } else {
      el.className = "result bad"
      el.textContent = `Invalid — ${c.reason}`
    }
  } catch (e) {
    el.className = "result bad"
    el.textContent = "Request failed: " + e.message
  }
})

function adminHeaders() {
  return { "Content-Type": "application/json", "x-admin-token": $("#adminToken").value.trim() }
}

function displayKeyResult(el, text, key) {
  el.className = "result ok"
  el.innerHTML = ""
  el.append(text)
  if (key) {
    const btn = document.createElement("button")
    btn.className = "copy-btn ghost"
    btn.textContent = "copy"
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(key)
        btn.textContent = "copied"
        setTimeout(() => (btn.textContent = "copy"), 1500)
      } catch {
        btn.textContent = "failed"
      }
    })
    el.appendChild(btn)
  }
}

$("#genBtn").addEventListener("click", async () => {
  const el = $("#genResult")
  const r = await json("/api/license/generate", {
    method: "POST",
    headers: adminHeaders(),
    body: JSON.stringify({ customer: $("#customer").value.trim(), months: Number($("#months").value) }),
  }).catch((e) => ({ error: e.message }))
  if (r.error) {
    el.className = "result bad"
    el.textContent = "Error: " + r.error
  } else {
    displayKeyResult(el, `Generated key\nVerified: ${r.verified.valid} · expires ${r.verified.data.expires}\n`, r.key)
    window.atlasKey = r.key
    $("#genResult").dataset.fullKey = r.key
  }
})

$("#renewBtn").addEventListener("click", async () => {
  const current = $("#genResult").dataset.fullKey || window.atlasKey
  const el = $("#genResult")
  if (!current) {
    el.className = "result bad"
    el.textContent = "Generate a key first, then renew re-signs the current one."
    return
  }
  const r = await json("/api/license/renew", {
    method: "POST",
    headers: adminHeaders(),
    body: JSON.stringify({ key: current, months: Number($("#months").value) }),
  }).catch((e) => ({ error: e.message }))
  if (r.error) {
    el.className = "result bad"
    el.textContent = "Error: " + r.error
  } else {
    displayKeyResult(el, `Renewed · expires ${r.verified.data.expires}\n`, r.key)
    $("#genResult").dataset.fullKey = r.key
    window.atlasKey = r.key
  }
})

function setLive(ok) {
  const dot = $("#liveDot")
  dot.className = "dot " + (ok ? "live" : "dead")
}

async function refreshAll(manual) {
  try {
    const [status, equity, trades, decisions, license] = await Promise.all([
      json("/api/status"),
      json("/api/equity"),
      json("/api/trades"),
      json("/api/decisions"),
      json("/api/license"),
    ])
    renderStatus(status)
    renderEquityChart(equity)
    renderTrades(trades)
    renderDecisions(decisions)
    renderLicense(license)
    setLive(true)
    const now = new Date()
    nextRefresh = now.getTime() + REFRESH_MS
    const countdown = Math.ceil(REFRESH_MS / 1000)
    $("#lastUpdate").textContent = "live · " + now.toLocaleTimeString() + " · refresh in " + countdown + "s"
  } catch (e) {
    setLive(false)
    $("#lastUpdate").textContent = "offline — " + e.message
  }
}

function tick() {
  if (Date.now() >= nextRefresh) {
    nextRefresh = Date.now() + REFRESH_MS
    refreshAll()
    return
  }
  if ($("#liveDot").classList.contains("live")) {
    const s = Math.max(0, Math.ceil((nextRefresh - Date.now()) / 1000))
    const t = $("#lastUpdate").textContent.replace(/refresh in \d+s$/, "refresh in " + s + "s")
    $("#lastUpdate").textContent = t
  }
}

setInterval(tick, 1000)
window.addEventListener("resize", () => {
  json("/api/equity").then((e) => renderEquityChart(e)).catch(() => {})
})
refreshAll()