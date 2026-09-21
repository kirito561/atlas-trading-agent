from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone


def _b64(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(payload: str) -> dict:
    padding = "=" * (-len(payload) % 4)
    raw = base64.urlsafe_b64decode(payload + padding)
    return json.loads(raw)


def _sign(payload: str, secret: str) -> str:
    computed = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return computed[:32]


def make_key(customer: str, months: int, secret: str, plan: str = "monthly") -> str:
    now = datetime.now(timezone.utc)
    issued = now.isoformat()
    expires = (now + timedelta(days=30 * months)).isoformat()
    payload = _b64({"customer": customer, "plan": plan, "issued": issued, "expires": expires})
    return "ATLAS.{}.{}".format(payload, _sign(payload, secret))


def verify_key(key: str, secret: str, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now
    if not key or not key.startswith("ATLAS."):
        return {"valid": False, "reason": "malformed"}
    parts = key.split(".")
    if len(parts) != 3:
        return {"valid": False, "reason": "malformed"}
    payload, signature = parts[1], parts[2]
    expected = _sign(payload, secret)
    if not hmac.compare_digest(signature, expected):
        return {"valid": False, "reason": "bad signature"}
    try:
        data = _unb64(payload)
        expires_ts = int(datetime.fromisoformat(data["expires"]).timestamp())
    except (KeyError, ValueError, json.JSONDecodeError):
        return {"valid": False, "reason": "corrupt payload"}
    remaining_days = (expires_ts - now) / 86400.0
    if remaining_days <= 0:
        data["remaining_days"] = 0.0
        return {"valid": False, "reason": "expired", "data": data}
    data["remaining_days"] = round(remaining_days, 2)
    return {"valid": True, "data": data, "reason": "ok"}