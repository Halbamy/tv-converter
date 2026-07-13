from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from types import ModuleType
import unittest
from unittest.mock import Mock

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = ModuleType("mysql")
    mysql_connector_module = ModuleType("mysql.connector")
    mysql_connector_module.connect = Mock()
    mysql_module.connector = mysql_connector_module
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_connector_module

from main import App
from recording_queue import RecordingQueue


class AppProcessingTest(unittest.TestCase):
    def test_plex_failure_does_not_prevent_source_deletion(self):
        recording = SimpleNamespace(
            source="test",
            recording_id="recording-1",
            filename=Path("/recording-1.ts"),
            title="Recording 1",
            deletepending=False,
        )
        converted = SimpleNamespace(
            source=recording,
            encoder_name="test-encoder",
            output_file=Path("/recording-1.mkv"),
        )
        plan = SimpleNamespace(action="transcode")

        app = App.__new__(App)
        app.queue = RecordingQueue()
        app.queue.add_new([recording])
        app.converter = Mock()
        app.converter.prepare.return_value = plan
        app.converter.convert.return_value = converted
        app.state_monitor = Mock()
        app.tvheadend = Mock()
        app.tvheadend.import_recording.return_value = True
        app.plex = Mock()
        app.plex.refresh.return_value = False
        app.mqtt = Mock()
        app.mqtt.state.state = "RUNNING"
        app.control = Mock()
        app._delete_source_if_configured = Mock()

        app._process_next(False, False, False)

        app.plex.refresh.assert_called_once_with()
        app._delete_source_if_configured.assert_called_once_with(converted)


if __name__ == "__main__":
    unittest.main()
