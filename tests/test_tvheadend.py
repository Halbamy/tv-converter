from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from models import ConvertedRecording, Recording
from tvheadend import TVHeadendImporter, TVHeadendStateMonitor


class TVHeadendStateMonitorTest(unittest.TestCase):
    def test_only_recording_status_is_busy(self):
        monitor = TVHeadendStateMonitor({"url": "http://tvh"})
        monitor._get_json = Mock(
            side_effect=[
                {
                    "entries": [
                        {"status": "Scheduled for recording", "sched_status": "scheduled"},
                        {"status": "Recording", "sched_status": "recording"},
                    ]
                },
                {"entries": []},
            ]
        )
        self.assertEqual(monitor.busy_counts(), (1, 0))

    @patch("tvheadend.time.sleep")
    def test_wait_callbacks_report_busy_and_ready(self, sleep):
        monitor = TVHeadendStateMonitor({"url": "http://tvh"}, poll_interval=10)
        monitor.busy_counts = Mock(side_effect=[(1, 2), (0, 0)])
        on_busy = Mock()
        on_ready = Mock()

        monitor.wait_until_not_busy(on_busy=on_busy, on_ready=on_ready)

        on_busy.assert_called_once_with(1, 2)
        on_ready.assert_called_once_with()
        sleep.assert_called_once_with(10)

    def test_ready_callback_is_not_used_without_waiting(self):
        monitor = TVHeadendStateMonitor({"url": "http://tvh"})
        monitor.busy_counts = Mock(return_value=(0, 0))
        on_ready = Mock()

        monitor.wait_until_not_busy(on_ready=on_ready)

        on_ready.assert_not_called()


class TVHeadendImporterTest(unittest.TestCase):
    def test_url_normalization_ignores_trailing_slash(self):
        importer = TVHeadendImporter(
            {"url": "http://TVH:9981/"},
            {"url": "http://tvh:9981"},
        )
        self.assertTrue(importer._same_instance())


if __name__ == "__main__":
    unittest.main()
