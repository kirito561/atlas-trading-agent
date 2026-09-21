const crypto = require("crypto")

const PREFIX = "ATLAS."

function b64(obj) {
  return Buffer.from(JSON.stringify(obj)).toString("base64url")
}

function un64(payload) {
  return JSON.parse(Buffer.from(payload, "base64url").toString("utf8"))
}

function sign(payload, secret) {
  return crypto.createHmac("sha256", secret).update(payload).digest("hex").slice(0, 32)
}

function generateKey(customer, months, secret, plan = "monthly") {
  const issued = new Date().toISOString()
  const expires = new Date(Date.now() + months * 30 * 24 * 3600 * 1000).toISOString()
  const payload = b64({ customer, plan, issued, expires })
  return `${PREFIX}${payload}.${sign(payload, secret)}`
}

function verifyKey(key, secret) {
  if (typeof key !== "string" || !key.startsWith(PREFIX)) {
    return { valid: false, reason: "malformed" }
  }
  const parts = key.split(".")
  if (parts.length !== 3) return { valid: false, reason: "malformed" }
  const [, payload, signature] = parts
  const expected = sign(payload, secret)
  const a = Buffer.from(signature)
  const b = Buffer.from(expected)
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return { valid: false, reason: "bad signature" }
  }
  let data
  try {
    data = un64(payload)
  } catch {
    return { valid: false, reason: "corrupt payload" }
  }
  const expiresTs = Date.parse(data.expires)
  if (Number.isNaN(expiresTs)) return { valid: false, reason: "corrupt payload", data }
  if (Date.now() > expiresTs) {
    data.remaining_days = 0
    return { valid: false, reason: "expired", data }
  }
  data.remaining_days = Math.round(((expiresTs - Date.now()) / 86400000) * 100) / 100
  return { valid: true, reason: "ok", data }
}

module.exports = { generateKey, verifyKey }