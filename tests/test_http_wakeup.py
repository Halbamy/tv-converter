from __future__ import annotations

import threading
import unittest
import urllib.error
import urllib.request

from http_wakeup import HTTPWakeupService, parse_allowed_network


class HTTPWakeupServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.event = threading.Event()
        self.service = HTTPWakeupService(
            {
                "enabled": True,
                "bind": "127.0.0.1",
                "allow": "127.0.0.1",
                "port": 0,
                "token": "test-token",
            },
            self.event,
        )
        self.service.start()
        assert self.service.server is not None
        self.url = f"http://127.0.0.1:{self.service.server.server_address[1]}/ping"

    def tearDown(self) -> None:
        self.service.stop()

    def request(self, *, token: str | None = None, method: str = "POST"):
        headers = {}

        if token is not None:
            headers["X-TV-Converter-Token"] = token

        request = urllib.request.Request(self.url, headers=headers, method=method)
        return urllib.request.urlopen(request, timeout=2)

    def test_valid_ping_sets_wakeup_event(self) -> None:
        with self.request(token="test-token") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"OK\n")

        self.assertTrue(self.event.is_set())

    def test_invalid_token_is_rejected(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request(token="wrong-token")

        self.assertEqual(context.exception.code, 401)
        self.assertFalse(self.event.is_set())

    def test_get_is_rejected(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request(token="test-token", method="GET")

        self.assertEqual(context.exception.code, 405)
        self.assertFalse(self.event.is_set())

    def test_disallowed_client_is_rejected(self) -> None:
        self.service.stop()
        self.service = HTTPWakeupService(
            {
                "enabled": True,
                "bind": "127.0.0.1",
                "allow": "192.0.2.0/24",
                "port": 0,
                "token": "test-token",
            },
            self.event,
        )
        self.service.start()
        assert self.service.server is not None
        self.url = f"http://127.0.0.1:{self.service.server.server_address[1]}/ping"

        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request(token="test-token")

        self.assertEqual(context.exception.code, 403)
        self.assertFalse(self.event.is_set())

    def test_zero_address_allows_entire_address_family(self) -> None:
        self.assertEqual(str(parse_allowed_network("0.0.0.0")), "0.0.0.0/0")
        self.assertEqual(str(parse_allowed_network("::")), "::/0")


if __name__ == "__main__":
    unittest.main()
