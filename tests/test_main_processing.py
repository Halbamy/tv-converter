from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
from types import SimpleNamespace
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = ModuleType("mysql")
    mysql_connector_module = ModuleType("mysql.connector")
    mysql_connector_module.connect = Mock()
    mysql_module.connector = mysql_connector_module
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_connector_module

import main as main_module
from config import ConfigError
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


class PlexCommandTest(unittest.TestCase):
    def test_refresh_plex_calls_only_forced_plex_refresh(self):
        config = {"postprocessing": {"plex": {"refresh_url": "https://plex/refresh"}}}
        processor = Mock()
        processor.refresh.return_value = True

        with (
            patch.object(sys, "argv", ["tv-converter", "--refresh-plex"]),
            patch.object(main_module, "configure_logging"),
            patch.object(main_module, "load_config", return_value=config) as load_config,
            patch.object(main_module, "PlexPostprocessor", return_value=processor) as plex,
            patch.object(main_module, "App") as app,
        ):
            result = main_module.main()

        self.assertEqual(result, 0)
        load_config.assert_called_once_with("config.yaml")
        plex.assert_called_once_with(config["postprocessing"])
        processor.refresh.assert_called_once_with(force=True)
        app.assert_not_called()


class ConfigurationErrorTest(unittest.TestCase):
    def test_unreadable_config_prints_error_and_full_help_without_traceback(self):
        stderr = StringIO()

        with (
            patch.object(sys, "argv", ["tv-converter"]),
            patch.object(main_module, "configure_logging"),
            patch.object(
                main_module,
                "App",
                side_effect=ConfigError(
                    "Could not read config file /etc/tv-converter/config.yaml: Permission denied"
                ),
            ),
            redirect_stderr(stderr),
        ):
            result = main_module.main()

        output = stderr.getvalue()
        self.assertEqual(result, 2)
        self.assertIn("configuration error", output)
        self.assertIn("Permission denied", output)
        self.assertIn("--repair-moved-recordings", output)
        self.assertIn("--refresh-plex", output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
