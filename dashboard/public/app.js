const $ = (sel) => document.querySelector(sel)
const fmt = (v, d = 2) => {
  if (v === undefined || v === null || Number.isNaN(Number(v))) return "—"
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: d })
}
const fmtPct = (v) => (v === undefined || v === null ? "—" : fmt(v, 2) + "%")
const fmtTime = (ts) => {
  if (!ts) return "—"
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.remove("active"))
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"))
    btn.classList.add("active")
    $("#view-" + btn.dataset.view).classList.add("active")
  })
})

async function json(url, opts) {
  const res = await fetch(url, opts)
  return res.json()
}

function card(k, v, cls) {
  const t = $("#cardTmpl").content.cloneNode(true)
  t.querySelector(".k").textContent = k
  const val = t.querySelector(".v")
  val.textContent = v
  if (cls) val.classList.add(cls)
  return t
}

function renderStatus() {
  json("/api/status").then((data) => {
    const s = data.status || {}
    const state = data.state || {}
    const cards = $("#cards")
    cards.innerHTML = ""
    const mode = s.halted ? "HALT" : (s.operating_mode || "—")
    const modeCls = s.halted ? "down" : s.operating_mode === "normal" ? "up" : "warn"
    cards.appendChild(card("Operating mode", mode.toUpperCase(), modeCls))
    cards.appendChild(card("Engine mode", (s.mode || "—").toUpperCase()))
    cards.appendChild(card("Equity", fmt(s.equity) + " USDT"))
    cards.appendChild(card("Cash", fmt(s.cash) + " USDT"))
    cards.appendChild(card("Peak equity", fmt(s.peak_equity)))
    cards.appendChild(card("Drawdown", fmtPct(s.drawdown ? s.drawdown * 100 : 0)))
    cards.appendChild(card("Exposure", fmtPct(s.exposure_pct)))
    cards.appendChild(card("Open positions", String(s.open_positions || 0)))
    cards.appendChild(card("Journal trades", fmt((data.journal || {}).total)))
    cards.appendChild(card("Net P&L (journal)", fmt((data.journal || {}).net), (data.journal || {}).net >= 0 ? "up" : "down"))
    cards.appendChild(card("Day P&L", fmt(s.day_pnl), s.day_pnl >= 0 ? "up" : "down"))
    cards.appendChild(card("Halt", s.halted ? (state.halt_reason || "YES") : "no", s.halted ? "down" : "up"))
    renderEquityCurve()
    renderPositions(data.open_positions)
  })
}

function renderEquityCurve() {
  json("/api/equity").then((rows) => {
    const canvas = $("#equityChart")
    const ctx = canvas.getContext("2d")
    const dpr = window.devicePixelRatio || 1
    canvas.width = canvas.clientWidth * dpr
    canvas.height = 220 * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, canvas.clientWidth, 220)
    const W = canvas.clientWidth
    const H = 220
    if (!rows || rows.length < 2) {
      ctx.fillStyle = "#666"
      ctx.fillText("Not enough data yet — run: atlas.py once", 16, 30)
      return
    }
    const values = rows.map((r) => r.equity)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || 1
    const x = (i) => (i / (values.length - 1)) * (W - 40) + 20
    const y = (v) => H - 20 - ((v - min) / span) * (H - 50)
    ctx.strokeStyle = "#22c55e"
    ctx.lineWidth = 2
    ctx.beginPath()
    values.forEach((v, i) => (i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v))))
    ctx.stroke()
    ctx.fillStyle = "#94a3b8"
    ctx.fillText("Equity (USDT)", 20, 16)
  })
}

function renderPositions(positions) {
  const tbody = $("#positionsTable tbody")
  tbody.innerHTML = ""
  const empty = $("#positionsEmpty")
  empty.style.display = positions.length ? "none" : "block"
  positions.forEach((p) => {
    const tr = document.createElement("tr")
    const cls = p.side === "long" ? "up" : "down"
    tr.innerHTML =
      `<td>${p.symbol}</td><td class="${cls}">${p.side}</td><td>${fmt(p.qty)}</td>` +
      `<td>${fmt(p.entry)}</td><td>${fmt(p.stop)}</td><td>${fmt(p.target)}</td><td>${fmt(p.last_price)}</td>` +
      `<td class="${p.unrealized_pnl >= 0 ? "up" : "down"}">${fmt(p.unrealized_pnl)}</td>` +
      `<td class="${p.unrealized_pnl >= 0 ? "up" : "down"}">${fmtPct(p.unrealized_pct)}</td>`
    tbody.appendChild(tr)
  })
}

function renderTrades() {
  json("/api/trades").then((rows) => {
    const tbody = $("#tradesBody")
    tbody.innerHTML = ""
    rows.forEach((t) => {
      const tr = document.createElement("tr")
      const cls = t.pnl >= 0 ? "up" : "down"
      tr.innerHTML =
        `<td>${fmtTime(t.opened_at)}</td><td>${t.symbol}</td>` +
        `<td class="${t.side === "long" ? "up" : "down"}">${t.side}</td><td>${fmt(t.qty)}</td>` +
        `<td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td>` +
        `<td class="${cls}">${fmt(t.pnl)}</td><td class="${cls}">${fmtPct(t.pnl_pct)}</td>` +
        `<td>${t.reason}</td><td>${t.conviction}/10</td>`
      tbody.appendChild(tr)
    })
  })
}

function renderDecisions() {
  json("/api/decisions").then((rows) => {
    const tbody = $("#decisionsBody")
    tbody.innerHTML = ""
    rows.forEach((d) => {
      const tr = document.createElement("tr")
      const cls = d.action === "enter" ? "up" : d.action === "error" ? "down" : ""
      tr.innerHTML =
        `<td>${fmtTime(d.ts)}</td><td>${d.symbol}</td>` +
        `<td class="${cls}">${d.action}</td><td>${d.conviction}/10</td>` +
        `<td class="detail">${escapeHtml(JSON.stringify(d.details || {}))}</td>`
      tbody.appendChild(tr)
    })
  })
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
}

function renderLicense() {
  json("/api/license").then((lic) => {
    const box = $("#licenseStatus")
    const c = lic.check || {}
    if (c.valid) {
      box.className = "license-box ok"
      box.textContent = `Active — ${lic.key} · expires ${c.data.expires} · ${c.data.remaining_days} days left`
    } else {
      box.className = "license-box bad"
      box.textContent = `No active license — ${c.reason || ""}`
    }
  })
}

$("#verifyBtn").addEventListener("click", async () => {
  const key = $("#verifyInput").value.trim()
  const r = await json("/api/license/verify?key=" + encodeURIComponent(key))
  const c = r.check || {}
  const el = $("#verifyResult")
  if (c.valid) {
    el.className = "ok"
    el.textContent = `Valid for ${c.data.customer} · expires ${c.data.expires} · ${c.data.remaining_days} days remaining`
  } else {
    el.className = "bad"
    el.textContent = `Invalid — ${c.reason}`
  }
})

function adminHeaders() {
  return { "Content-Type": "application/json", "x-admin-token": $("#adminToken").value.trim() }
}

$("#genBtn").addEventListener("click", async () => {
  const r = await json("/api/license/generate", {
    method: "POST",
    headers: adminHeaders(),
    body: JSON.stringify({ customer: $("#customer").value.trim(), months: Number($("#months").value) }),
  })
  const el = $("#genResult")
  if (r.error) {
    el.className = "bad"
    el.textContent = "Error: " + r.error
  } else {
    el.className = "ok"
    const out = `${r.key}\nVerified: ${r.verified.valid} · expires ${r.verified.data.expires}`
    el.textContent = out
    el.dataset.fullKey = r.key
  }
})

$("#renewBtn").addEventListener("click", async () => {
  const current = $("#genResult").dataset.fullKey
  if (!current) {
    alert("Generate or verify a key first, then renew uses the current license.key.")
    return
  }
  const r = await json("/api/license/renew", {
    method: "POST",
    headers: adminHeaders(),
    body: JSON.stringify({ key: current, months: Number($("#months").value) }),
  })
  const el = $("#genResult")
  if (r.error) {
    el.className = "bad"
    el.textContent = "Error: " + r.error
  } else {
    el.className = "ok"
    el.textContent = `${r.key}\nRenewed → expires ${r.verified.data.expires}`
    el.dataset.fullKey = r.key
  }
})

function refreshAll() {
  renderStatus()
  renderTrades()
  renderDecisions()
  renderLicense()
}

setInterval(refreshAll, 30000)
refreshAll()