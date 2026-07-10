from __future__ import annotations

import requests

from event_logger import logger


class PlexPostprocessor:
    def __init__(self, config: dict):
        cfg = (config or {}).get("plex", {})
        self.enabled = bool(cfg.get("enabled", False))
        self.refresh_url = cfg.get("refresh_url")
        self.verify_ssl = bool(cfg.get("verify_ssl", False))
        self.timeout = int(cfg.get("timeout", 10))

    def refresh(self) -> bool:
        if not self.enabled:
            return True

        if not self.refresh_url:
            logger.error("Plex refresh is enabled but refresh_url is empty.")
            return False

        try:
            response = requests.get(
                self.refresh_url,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            logger.info("Plex refresh completed.")
            return True
        except Exception as exc:
            logger.error("Plex refresh failed: %s", exc)
            return False
