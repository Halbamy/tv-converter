from __future__ import annotations

import json
import threading
import unittest

from tvheadend_events import TVHeadendEventListener


class TVHeadendEventListenerTest(unittest.TestCase):
    def test_websocket_url(self):
        self.assertEqual(
            TVHeadendEventListener._websocket_url("http://192.168.0.33:9981/"),
            "ws://192.168.0.33:9981/comet/ws",
        )
        self.assertEqual(
            TVHeadendEventListener._websocket_url("https://tvh.example.test"),
            "wss://tvh.example.test/comet/ws",
        )

    def test_relevant_event_marks_source_dirty(self):
        listener = TVHeadendEventListener("http://127.0.0.1:9981")
        listener.mark_scanned()
        listener._on_message(
            None,
            json.dumps(
                {
                    "messages": [
                        {
                            "notificationClass": "dvrentry",
                            "change": ["123"],
                        }
                    ]
                }
            ),
        )
        self.assertTrue(listener.changes_pending())

    def test_irrelevant_event_is_ignored(self):
        listener = TVHeadendEventListener("http://127.0.0.1:9981")
        listener.mark_scanned()
        listener._on_message(
            None,
            json.dumps(
                {
                    "messages": [
                        {
                            "notificationClass": "diskspaceUpdate",
                        }
                    ]
                }
            ),
        )
        self.assertFalse(listener.changes_pending())

    def test_control_event_interrupts_wait(self):
        listener = TVHeadendEventListener("http://127.0.0.1:9981")
        listener.mark_scanned()
        control = threading.Event()
        control.set()
        self.assertFalse(listener.wait(control))


if __name__ == "__main__":
    unittest.main()
