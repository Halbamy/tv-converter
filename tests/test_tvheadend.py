from __future__ import annotations

import unittest
from unittest.mock import Mock

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


class TVHeadendImporterTest(unittest.TestCase):
    def test_url_normalization_ignores_trailing_slash(self):
        importer = TVHeadendImporter(
            {"url": "http://TVH:9981/"},
            {"url": "http://tvh:9981"},
        )
        self.assertTrue(importer._same_instance())


if __name__ == "__main__":
    unittest.main()
