from __future__ import annotations

import hmac
import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from event_logger import logger


TOKEN_HEADER = "X-TV-Converter-Token"


def parse_allowed_network(value: str):
    value = value.strip()

    if value == "0.0.0.0":
        value = "0.0.0.0/0"
    elif value == "::":
        value = "::/0"
    elif "/" not in value:
        address = ipaddress.ip_address(value)
        value = f"{value}/{address.max_prefixlen}"

    return ipaddress.ip_network(value, strict=False)


class WakeupHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, *, allowed_network, token, wakeup_event):
        bind_address = ipaddress.ip_address(server_address[0])
        self.address_family = socket.AF_INET6 if bind_address.version == 6 else socket.AF_INET
        self.allowed_network = allowed_network
        self.token = token
        self.wakeup_event = wakeup_event
        super().__init__(server_address, handler_class)


class WakeupRequestHandler(BaseHTTPRequestHandler):
    server: WakeupHTTPServer
    server_version = "tv-converter"
    sys_version = ""

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/ping":
            self.send_error(404, "Not Found")
            return

        client_ip = self.client_address[0].split("%", 1)[0]
        client_address = ipaddress.ip_address(client_ip)

        if client_address not in self.server.allowed_network:
            logger.warning("Rejected HTTP wakeup from disallowed address: %s", client_ip)
            self.send_error(403, "Forbidden")
            return

        supplied_token = self.headers.get(TOKEN_HEADER, "")

        if not hmac.compare_digest(supplied_token, self.server.token):
            logger.warning("Rejected HTTP wakeup with invalid token from: %s", client_ip)
            self.send_error(401, "Unauthorized")
            return

        self.server.wakeup_event.set()
        logger.info("HTTP wakeup received from %s.", client_ip)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "3")
        self.end_headers()
        self.wfile.write(b"OK\n")

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/ping":
            self.send_error(405, "Method Not Allowed")
        else:
            self.send_error(404, "Not Found")

    def log_message(self, format: str, *args) -> None:
        logger.debug("HTTP wakeup: " + format, *args)


class HTTPWakeupService:
    def __init__(self, config: dict, wakeup_event: threading.Event):
        self.config = config or {}
        self.wakeup_event = wakeup_event
        self.server: WakeupHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    def start(self) -> None:
        if not self.enabled:
            return

        bind = str(self.config.get("bind", "0.0.0.0"))
        port = int(self.config.get("port", 8080))
        allowed_network = parse_allowed_network(str(self.config.get("allow", "0.0.0.0/0")))
        token = str(self.config.get("token", ""))

        self.server = WakeupHTTPServer(
            (bind, port),
            WakeupRequestHandler,
            allowed_network=allowed_network,
            token=token,
            wakeup_event=self.wakeup_event,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="tv-converter-http-wakeup",
            daemon=True,
        )
        self.thread.start()
        logger.info(
            "HTTP wakeup listening on %s:%s; allowed network: %s.",
            bind,
            port,
            allowed_network,
        )

    def stop(self) -> None:
        if self.server is None:
            return

        self.server.shutdown()
        self.server.server_close()

        if self.thread is not None:
            self.thread.join(timeout=5)

        self.server = None
        self.thread = None
