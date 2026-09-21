const express = require("express")
const fs = require("fs")
const path = require("path")
const { DatabaseSync } = require("node:sqlite")
const { generateKey, verifyKey } = require("./lib/license")

const ROOT = path.resolve(__dirname, "..")
const DATA_DIR = path.join(ROOT, "data")

function loadEnv() {
  const envPath = path.join(ROOT, ".env")
  const out = {}
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/)
      if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, "")
    }
  }
  return out
}

const env = loadEnv()
const LICENSE_SECRET = env.ATLAS_LICENSE_SECRET || "change-me-please"
const ADMIN_TOKEN = env.ATLAS_ADMIN_TOKEN || "change-me-please"
const PORT = Number(env.DASHBOARD_PORT || 4173)

const app = express()
app.use(express.json())
app.use(express.static(path.join(__dirname, "public")))

let db = null
const dbPath = path.join(DATA_DIR, "atlas.db")
if (fs.existsSync(dbPath)) {
  db = new DatabaseSync(dbPath, { readOnly: true })
}

function readJson(rel) {
  const p = path.join(DATA_DIR, rel)
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"))
  } catch {
    return null
  }
}

function readRows(sql) {
  if (!db) return []
  try {
    return db.prepare(sql).all()
  } catch {
    return []
  }
}

app.get("/api/status", (req, res) => {
  const status = readJson("status.json") || {}
  const state = readJson("state.json") || {}
  const posRows = readRows("SELECT data FROM positions ORDER BY id DESC LIMIT 1")
  const open = posRows.length ? JSON.parse(posRows[0].data) : []
  const summary = db
    ? db.prepare("SELECT COUNT(*) total, COALESCE(SUM(pnl),0) net FROM trades").get()
    : { total: 0, net: 0 }
  res.json({
    status,
    state,
    open_positions: open,
    journal: summary,
    license: loadLicenseState(),
  })
})

app.get("/api/equity", (req, res) => {
  res.json(readRows("SELECT ts, equity, cash, operating_mode FROM equity ORDER BY ts DESC LIMIT 2000"))
})

app.get("/api/trades", (req, res) => {
  res.json(readRows("SELECT * FROM trades ORDER BY closed_at DESC LIMIT 200"))
})

app.get("/api/decisions", (req, res) => {
  res.json(readRows("SELECT ts, symbol, action, conviction, details FROM decisions ORDER BY ts DESC LIMIT 200"))
})

app.post("/api/license/generate", (req, res) => {
  const auth = req.get("x-admin-token")
  if (auth !== ADMIN_TOKEN) return res.status(401).json({ error: "unauthorized" })
  const { customer, months = 1, plan = "monthly" } = req.body || {}
  if (!customer) return res.status(400).json({ error: "customer required" })
  const key = generateKey(String(customer), Number(months), LICENSE_SECRET, String(plan))
  res.json({ key, verified: verifyKey(key, LICENSE_SECRET) })
})

app.post("/api/license/renew", (req, res) => {
  const auth = req.get("x-admin-token")
  if (auth !== ADMIN_TOKEN) return res.status(401).json({ error: "unauthorized" })
  const { key, months = 1 } = req.body || {}
  const check = verifyKey(String(key || ""), LICENSE_SECRET)
  if (!check.valid) return res.status(400).json({ error: "current key invalid", check })
  const renewed = generateKey(check.data.customer, Number(months), LICENSE_SECRET, check.data.plan || "monthly")
  res.json({ key: renewed, verified: verifyKey(renewed, LICENSE_SECRET) })
})

app.get("/api/license/verify", (req, res) => {
  const key = String(req.query.key || "")
  res.json({ key: key.slice(0, 24) + "...", check: verifyKey(key, LICENSE_SECRET) })
})

function loadLicenseState() {
  const keyFile = path.join(DATA_DIR, "license.key")
  if (fs.existsSync(keyFile)) {
    const key = fs.readFileSync(keyFile, "utf8").trim()
    return { key: key.slice(0, 24) + "...", check: verifyKey(key, LICENSE_SECRET) }
  }
  return { key: null, check: { valid: false, reason: "no license key configured" } }
}

app.get("/api/license", (req, res) => {
  res.json(loadLicenseState())
})

app.listen(PORT, () => {
  console.log(`ATLAS dashboard on http://localhost:${PORT}`)
})