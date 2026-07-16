from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from event_logger import logger

if TYPE_CHECKING:
    from websocket import WebSocketApp


class TVHeadendEventListener:
    """Listen to TVHeadend comet events and coalesce them into one dirty flag."""

    RELEVANT_CLASSES = {"dvrentry", "subscriptions", "connections"}

    def __init__(self, base_url: str):
        self.url = self._websocket_url(base_url)
        self._changed = threading.Event()
        self._state_changed = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: WebSocketApp | None = None
        self._websocket_app_class: type[WebSocketApp] | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        try:
            from websocket import WebSocketApp
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "TVHeadend event handling requires the websocket-client package."
            ) from exc

        self._websocket_app_class = WebSocketApp
        self._stop.clear()
        self._state_changed.clear()
        self._changed.set()
        self._thread = threading.Thread(
            target=self._run,
            name="tvheadend-events",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._changed.set()
        self._state_changed.set()

        if self._socket is not None:
            self._socket.close()

        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def wait(self, control_event: threading.Event) -> bool:
        while not self._stop.is_set() and not control_event.is_set():
            if self._changed.wait(timeout=1):
                return True

        return False

    def changes_pending(self) -> bool:
        return self._changed.is_set()

    def mark_scanned(self) -> None:
        self._changed.clear()
        self._state_changed.clear()

    @property
    def state_change_event(self) -> threading.Event:
        return self._state_changed

    def _run(self) -> None:
        assert self._websocket_app_class is not None

        while not self._stop.is_set():
            self._socket = self._websocket_app_class(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._socket.run_forever()
            self._socket = None

            if not self._stop.wait(5):
                logger.info("Reconnecting TVHeadend WebSocket.")

    def _on_open(self, websocket) -> None:
        logger.info("Connected to TVHeadend WebSocket: %s", self.url)
        self._changed.set()

    def _on_message(self, websocket, message: str) -> None:
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid TVHeadend WebSocket message.")
            return

        for event in payload.get("messages", []):
            notification_class = event.get("notificationClass")

            if notification_class in self.RELEVANT_CLASSES:
                logger.debug("TVHeadend event received: %s", notification_class)
                self._changed.set()
                self._state_changed.set()
                return

    def _on_error(self, websocket, error) -> None:
        if not self._stop.is_set():
            logger.warning("TVHeadend WebSocket error: %s", error)

    def _on_close(self, websocket, status_code, reason) -> None:
        if not self._stop.is_set():
            logger.warning(
                "TVHeadend WebSocket disconnected (status=%s, reason=%s).",
                status_code,
                reason,
            )

    @staticmethod
    def _websocket_url(base_url: str) -> str:
        parsed = urlsplit(base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunsplit((scheme, parsed.netloc, "/comet/ws", "", ""))
