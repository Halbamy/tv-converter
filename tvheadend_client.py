from __future__ import annotations

from typing import Any

import requests


class TVHeadendClient:
    def __init__(self, config: dict):
        self.config = config or {}
        self.base_url = str(self.config.get("url", "")).rstrip("/")
        self.authentication = self.config.get("authentication") or {}

    def get(self, path: str, params: dict[str, Any] | None = None, timeout: int = 30):
        return requests.get(
            self._url(path),
            params=params or {},
            auth=self._basic_auth(),
            headers=self._headers(),
            timeout=timeout,
        )

    def post(
        self,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        timeout: int = 30,
    ):
        return requests.post(
            self._url(path),
            data=data or {},
            auth=self._basic_auth(),
            headers=self._headers(),
            timeout=timeout,
        )

    def _url(self, path: str) -> str:
        if not self.base_url:
            raise RuntimeError("TVHeadend URL is not configured.")

        if path.startswith("/"):
            return self.base_url + path

        return self.base_url + "/" + path

    def _basic_auth(self):
        auth_type = self.authentication.get("type", "basic")

        if auth_type != "basic":
            return None

        username = self.authentication.get("username")
        password = self.authentication.get("password")

        if username or password:
            return (username, password)

        # Backward compatibility with old config.yaml files.
        username = self.config.get("username")
        password = self.config.get("password")

        if username or password:
            return (username, password)

        return None

    def _headers(self) -> dict[str, str]:
        auth_type = self.authentication.get("type", "basic")

        if auth_type != "persistent_auth":
            return {}

        auth_code = self.authentication.get("auth_code")

        if not auth_code:
            return {}

        return {"X-Persistent-Auth": str(auth_code)}
