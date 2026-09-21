from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..config import Config

log = logging.getLogger("atlas.notifier")


class Notifier:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def notify(self, message: str, urgency: str = "info") -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{urgency.upper()}] {stamp} {message}"
        if urgency == "critical":
            log.critical(line)
        elif urgency == "warning":
            log.warning(line)
        else:
            log.info(line)
        if self.cfg.notify_telegram_bot_token and self.cfg.notify_telegram_chat_id:
            self._telegram(message)

    def _telegram(self, text: str) -> None:
        try:
            url = "https://api.telegram.org/bot{}/sendMessage".format(self.cfg.notify_telegram_bot_token)
            data = urllib.parse.urlencode({"chat_id": self.cfg.notify_telegram_chat_id, "text": text}).encode()
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.warning("telegram notify failed: %s", e)