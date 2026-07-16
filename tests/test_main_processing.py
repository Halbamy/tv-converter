from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import threading
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
    def test_removed_recording_cleans_partial_and_leaves_next_item_queued(self):
        with TemporaryDirectory() as tmp:
            part = Path(tmp) / "converted.mkv.part"
            first = SimpleNamespace(
                source="test",
                recording_id="first",
                filename=Path(tmp) / "first.ts",
                title="First",
                deletepending=False,
            )
            second = SimpleNamespace(
                source="test",
                recording_id="second",
                filename=Path(tmp) / "second.ts",
                title="Second",
                deletepending=False,
            )
            plan = SimpleNamespace(
                action="transcode",
                output_file=Path(tmp) / "converted.mkv",
                temp_file=part,
            )
            app = App.__new__(App)
            app.queue = RecordingQueue()
            app.queue.add_new([first, second])
            app.converter = Mock()
            app.converter.prepare.return_value = plan
            app.state_monitor = Mock(change_event=None)
            app.state_monitor.wait_until_not_busy.return_value = True
            app.stop_event = threading.Event()
            app.mqtt = Mock()
            app.control = SimpleNamespace(stop_requested=False)

            def removed_during_conversion(*_args):
                part.touch()
                app._recording_removed.set()
                raise RuntimeError("ffmpeg terminated")

            app.converter.convert.side_effect = removed_during_conversion

            app._process_next(False, False, False)

            self.assertFalse(part.exists())
            self.assertFalse(app.control.stop_requested)
            self.assertEqual(len(app.queue), 1)
            self.assertIs(app.queue.pop(), second)

    def test_tvh_resume_aborts_when_recording_was_deleted(self):
        recording = SimpleNamespace(
            recording_id="deleted-uuid",
            filename=Path("/missing-recording.ts"),
        )
        change_event = threading.Event()
        change_event.set()
        app = App.__new__(App)
        app.state_monitor = SimpleNamespace(
            change_event=change_event,
            poll_interval=300,
            busy_counts=Mock(return_value=(0, 0)),
            recording_exists=Mock(return_value=False),
        )
        app.mqtt = Mock()
        app.mqtt.is_paused_for.return_value = True
        app.converter = Mock()
        app.stop_event = threading.Event()
        app._tvh_monitor_stop = threading.Event()
        app._recording_removed = threading.Event()

        app._monitor_tvh_during_conversion(recording)

        self.assertTrue(app._recording_removed.is_set())
        app.converter.runner.terminate.assert_called_once_with()
        app.mqtt.resume.assert_not_called()

    def test_dry_run_source_deletion_is_logged_without_deleting(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ts"
            target = Path(tmp) / "converted.mkv"
            source.touch()
            recording = SimpleNamespace(
                source="tvheadend",
                filename=source,
                deletepending=False,
            )
            config = {
                "destination": {
                    "type": "tvheadend",
                    "tvheadend": {"delete_source_after_import": True},
                }
            }

            with patch.object(main_module.logger, "info") as log_info:
                main_module.delete_source_if_configured(
                    config,
                    recording,
                    target,
                    dry_run=True,
                )

            self.assertTrue(source.exists())
            log_info.assert_called_once_with(
                "Would delete source file after successful TVHeadend update: %s",
                source,
            )

    def test_dry_run_plan_displays_audio_copy_target(self):
        recording = SimpleNamespace(
            source="tvheadend",
            starttime="2026-07-15 12:00:00",
            title="Recording",
            filename=Path("/recording.mkv"),
        )
        media = SimpleNamespace(
            video_codec="hevc",
            width=1280,
            height=720,
            audio_stream_index=1,
            audio_codec="aac",
            audio_copy=True,
            profile=SimpleNamespace(name="hd"),
        )
        plan = SimpleNamespace(
            action="transcode",
            output_file=Path("/converted.mkv"),
            temp_file=Path("/converted.mkv.part"),
            encoder_name="copy",
            media=media,
            command=[],
        )
        app = App.__new__(App)
        stdout = StringIO()

        with redirect_stdout(stdout):
            app._print_plan(recording, plan, 1, 1, False, False)

        self.assertIn("Audio: stream 1 aac -> copy", stdout.getvalue())

    def test_plex_refresh_runs_after_source_deletion(self):
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
        app.state_monitor.wait_until_not_busy.return_value = True
        app.stop_event = threading.Event()
        app.tvheadend = Mock()
        app.tvheadend.import_recording.return_value = True
        app.plex = Mock()
        app.plex.refresh.return_value = False
        app.mqtt = Mock()
        app.mqtt.state.state = "RUNNING"
        app.control = Mock()
        app._delete_source_if_configured = Mock()
        steps = []
        app._delete_source_if_configured.side_effect = lambda converted: steps.append("delete")
        app.plex.refresh.side_effect = lambda: steps.append("plex") or False

        app._process_next(False, False, False)

        app.plex.refresh.assert_called_once_with()
        app._delete_source_if_configured.assert_called_once_with(converted)
        self.assertEqual(steps, ["delete", "plex"])

    def test_mythtv_source_deletion_is_disabled(self):
        with TemporaryDirectory() as tmp:
            source_file = Path(tmp) / "recording.ts"
            output_file = Path(tmp) / "recording.mkv"
            source_file.touch()
            recording = SimpleNamespace(
                source="mythtv",
                recording_id="1234",
                title="Recording",
                filename=source_file,
                deletepending=False,
            )
            converted = SimpleNamespace(source=recording, output_file=output_file)
            app = App.__new__(App)
            app.config = {
                "destination": {
                    "type": "tvheadend",
                    "tvheadend": {"delete_source_after_import": True},
                }
            }

            app._delete_source_if_configured(converted)

            self.assertTrue(source_file.exists())


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


class SearchCommandTest(unittest.TestCase):
    def test_search_option_runs_dvr_search_directly(self):
        config = {"destination": {"type": "tvheadend"}}
        tvheadend_config = {"enabled": True, "url": "http://tvh"}
        searcher = Mock()
        searcher.search.return_value = [
            {
                "uuid": "recording-1",
                "title": "Tatort",
                "channelname": "Das Erste",
                "start": 100,
                "stop": 200,
                "filename": "/recordings/tatort.ts",
                "status": "Completed OK",
                "filesize": 123456,
                "fileremoved": False,
                "removal": 0,
                "duplicate": 0,
                "comment": "Imported",
                "data_errors": 2,
                "errors": 1,
                "errorcode": 7,
            }
        ]
        stdout = StringIO()

        with (
            patch.object(sys, "argv", ["tv-converter", "--search", "Tatort"]),
            patch.object(main_module, "configure_logging"),
            patch.object(main_module, "load_config", return_value=config),
            patch.object(
                main_module,
                "destination_config",
                return_value=tvheadend_config,
            ),
            patch.object(
                main_module,
                "TVHeadendRecordingSearcher",
                return_value=searcher,
            ) as searcher_class,
            patch.object(main_module, "App") as app,
            redirect_stdout(stdout),
        ):
            result = main_module.main()

        self.assertEqual(result, 0)
        searcher_class.assert_called_once_with(tvheadend_config)
        searcher.search.assert_called_once_with("Tatort")
        app.assert_not_called()
        output = stdout.getvalue()
        self.assertIn("  Status: Completed OK", output)
        self.assertIn("  Filesize: 123456", output)
        self.assertIn("  File removed: False", output)
        self.assertIn("  Removal: 0", output)
        self.assertIn("  Duplicate: 0", output)
        self.assertIn("  Comment: Imported", output)
        self.assertIn("  Data errors: 2", output)
        self.assertIn("  Errors: 1", output)
        self.assertIn("  Error code: 7", output)


class TranscodeCommandTest(unittest.TestCase):
    def test_transcode_updates_existing_tvheadend_entry(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ts"
            output = Path(tmp) / "converted.mkv"
            source.touch()
            output.touch()
            config = {"destination": {"type": "tvheadend"}, "mqtt": {}}
            tvheadend_config = {
                "enabled": True,
                "url": "http://tvh:9981",
                "delete_source_after_import": True,
            }
            recording = SimpleNamespace(
                source="tvheadend",
                recording_id="existing-uuid",
                title="Recording",
                filename=source,
                deletepending=False,
            )
            converted = SimpleNamespace(source=recording, output_file=output)
            plan = SimpleNamespace()
            transcoder = Mock()
            transcoder.get_recording_by_uuid.return_value = recording
            converter = Mock()
            converter.prepare.return_value = plan
            converter.convert.return_value = converted
            mqtt = Mock()
            importer = Mock()
            importer.import_recording.return_value = True
            plex = Mock()
            plex.refresh.side_effect = lambda: not source.exists()

            with (
                patch.object(
                    sys,
                    "argv",
                    ["tv-converter", "--transcode", "--uuid", "existing-uuid"],
                ),
                patch.object(main_module, "configure_logging"),
                patch.object(main_module, "load_config", return_value=config),
                patch.object(
                    main_module,
                    "destination_config",
                    return_value=tvheadend_config,
                ),
                patch.object(
                    main_module,
                    "TVHeadendRecordingTranscoder",
                    return_value=transcoder,
                ),
                patch.object(main_module, "MQTTController", return_value=mqtt),
                patch.object(main_module, "Converter", return_value=converter),
                patch.object(
                    main_module,
                    "TVHeadendImporter",
                    return_value=importer,
                ) as importer_class,
                patch.object(
                    main_module,
                    "PlexPostprocessor",
                    return_value=plex,
                ) as plex_class,
            ):
                result = main_module.main()

            self.assertEqual(result, 0)
            converter.convert.assert_called_once_with(recording, 1, 1, plan)
            importer_class.assert_called_once_with(tvheadend_config, tvheadend_config)
            importer.import_recording.assert_called_once_with(recording, converted)
            plex_class.assert_called_once_with({})
            plex.refresh.assert_called_once_with()
            self.assertFalse(source.exists())
            self.assertTrue(output.exists())


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
