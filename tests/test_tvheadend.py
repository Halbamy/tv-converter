from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from models import ConvertedRecording, Recording
from tvheadend import (
    TVHeadendImporter,
    TVHeadendMovedRecordingRepair,
    TVHeadendRecordingSearcher,
    TVHeadendStateMonitor,
)


class TVHeadendStateMonitorTest(unittest.TestCase):
    def test_recording_exists_checks_finished_uuid_and_removal_flag(self):
        monitor = TVHeadendStateMonitor({"url": "http://tvh"})
        response = Mock()
        response.json.return_value = {
            "entries": [
                {"uuid": "available", "fileremoved": False},
                {"uuid": "removed", "fileremoved": True},
            ]
        }
        monitor.client = Mock()
        monitor.client.get.return_value = response

        self.assertTrue(monitor.recording_exists("available"))
        self.assertFalse(monitor.recording_exists("removed"))

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
        monitor = TVHeadendStateMonitor(
            {"url": "http://tvh"},
            poll_interval=10,
            busy_recheck_interval=10,
        )
        monitor.busy_counts = Mock(side_effect=[(1, 2), (0, 0)])
        on_busy = Mock()
        on_ready = Mock()

        ready = monitor.wait_until_not_busy(on_busy=on_busy, on_ready=on_ready)

        self.assertTrue(ready)
        on_busy.assert_called_once_with(1, 2)
        on_ready.assert_called_once_with()
        sleep.assert_called_once_with(10)

    def test_ready_callback_is_not_used_without_waiting(self):
        monitor = TVHeadendStateMonitor({"url": "http://tvh"})
        monitor.busy_counts = Mock(return_value=(0, 0))
        on_ready = Mock()

        ready = monitor.wait_until_not_busy(on_ready=on_ready)

        self.assertTrue(ready)
        on_ready.assert_not_called()

    def test_stop_event_interrupts_busy_wait(self):
        monitor = TVHeadendStateMonitor({"url": "http://tvh"}, poll_interval=300)
        monitor.busy_counts = Mock(return_value=(1, 1))
        stop_event = threading.Event()
        stop_event.set()

        ready = monitor.wait_until_not_busy(stop_event=stop_event)

        self.assertFalse(ready)
        monitor.busy_counts.assert_not_called()

    def test_busy_state_uses_periodic_recheck_instead_of_websocket(self):
        change_event = threading.Event()
        monitor = TVHeadendStateMonitor(
            {"url": "http://tvh"},
            poll_interval=300,
            busy_recheck_interval=0,
            change_event=change_event,
        )
        monitor.busy_counts = Mock(side_effect=[(1, 1), (0, 0)])
        on_busy = Mock(side_effect=lambda *_: change_event.set())

        ready = monitor.wait_until_not_busy(
            on_busy=on_busy,
            stop_event=threading.Event(),
        )

        self.assertTrue(ready)
        self.assertEqual(monitor.busy_counts.call_count, 2)

    def test_identical_websocket_busy_events_are_logged_only_once(self):
        change_event = threading.Event()
        monitor = TVHeadendStateMonitor(
            {"url": "http://tvh"},
            poll_interval=300,
            busy_recheck_interval=0,
            change_event=change_event,
        )
        monitor.busy_counts = Mock(side_effect=[(1, 1), (1, 1), (0, 0)])
        on_busy = Mock(side_effect=lambda *_: change_event.set())

        with patch("tvheadend.logger.info") as log_info:
            ready = monitor.wait_until_not_busy(
                on_busy=on_busy,
                stop_event=threading.Event(),
            )

        self.assertTrue(ready)
        log_info.assert_called_once_with(
            "TVHeadend busy (recordings=%s, subscriptions=%s), waiting %s seconds.",
            1,
            1,
            0,
        )


class TVHeadendImporterTest(unittest.TestCase):
    def test_url_normalization_ignores_trailing_slash(self):
        importer = TVHeadendImporter(
            {"url": "http://TVH:9981/"},
            {"url": "http://tvh:9981"},
        )
        self.assertTrue(importer._same_instance())

    def test_same_tvheadend_instance_updates_existing_recording_path(self):
        config = {"url": "http://tvh:9981"}
        importer = TVHeadendImporter(config, config)
        importer.client = Mock()
        response = Mock()
        importer.client.post.return_value = response
        recording = SimpleNamespace(
            source="tvheadend",
            recording_id="existing-uuid",
            filename=Path("/recordings/source.ts"),
            title="Recording",
            deletepending=False,
        )
        converted = SimpleNamespace(output_file=Path("/recordings/converted.mkv"))

        result = importer.import_recording(recording, converted)

        self.assertTrue(result)
        importer.client.post.assert_called_once_with(
            "/api/dvr/entry/filemoved",
            data={
                "src": "/recordings/source.ts",
                "dst": "/recordings/converted.mkv",
            },
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()


class TVHeadendRecordingSearcherTest(unittest.TestCase):
    def test_search_fetches_all_dvr_entries(self):
        searcher = TVHeadendRecordingSearcher({"url": "http://tvh"})
        searcher.client = Mock()
        response = Mock()
        response.json.return_value = {
            "entries": [
                {
                    "uuid": "failed-1",
                    "title": {"eng": "Tatort"},
                    "status": "Missed",
                    "start": 100,
                    "stop": 200,
                    "fileremoved": False,
                    "removal": 3600,
                    "duplicate": 0,
                    "comment": "Imported recording",
                    "files": [
                        {
                            "filename": "/recordings/tatort.ts",
                            "filesize": 123456,
                            "data_errors": 2,
                            "errors": 1,
                            "errorcode": 7,
                        }
                    ],
                },
                {
                    "uuid": "upcoming-1",
                    "title": {"eng": "News"},
                    "status": "Scheduled for recording",
                    "start": 300,
                    "stop": 400,
                },
            ]
        }
        searcher.client.get.return_value = response

        results = searcher.search("tatort")

        searcher.client.get.assert_called_once_with(
            "/api/dvr/entry/grid",
            params={"limit": 999999, "sort": "start", "dir": "ASC"},
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()
        self.assertEqual([result["uuid"] for result in results], ["failed-1"])
        self.assertEqual(
            {
                field: results[0][field]
                for field in (
                    "status",
                    "filesize",
                    "fileremoved",
                    "removal",
                    "duplicate",
                    "comment",
                    "data_errors",
                    "errors",
                    "errorcode",
                )
            },
            {
                "status": "Missed",
                "filesize": 123456,
                "fileremoved": False,
                "removal": 3600,
                "duplicate": 0,
                "comment": "Imported recording",
                "data_errors": 2,
                "errors": 1,
                "errorcode": 7,
            },
        )


class TVHeadendMovedRecordingRepairTest(unittest.TestCase):
    def test_original_mode_finds_file_below_registered_parent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "recordings"
            root.mkdir()
            source = root / "recording" / "episode.ts"
            source.parent.mkdir()
            match = source.parent / "series" / "episode.ts"
            match.parent.mkdir()
            match.touch()
            repair = self._repair_for(source)

            result = repair.repair([], search_registered_parent=True)

            self.assertEqual(result.found, 1)
            self.assertEqual(result.updated, 1)
            repair.client.post.assert_called_once_with(
                "/api/dvr/entry/filemoved",
                data={"src": str(source), "dst": str(match)},
                timeout=30,
            )

    def test_updates_first_matching_file_from_search_directory_order(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            first_root = base / "first"
            second_root = base / "second"
            first_match = first_root / "nested" / "episode[1].ts"
            second_match = second_root / "episode[1].ts"
            first_match.parent.mkdir(parents=True)
            second_match.parent.mkdir(parents=True)
            first_match.touch()
            second_match.touch()
            source = base / "missing" / "episode[1].ts"
            repair = self._repair_for(source)

            result = repair.repair([first_root, second_root])

            self.assertEqual(result.checked, 1)
            self.assertEqual(result.missing, 1)
            self.assertEqual(result.found, 1)
            self.assertEqual(result.updated, 1)
            repair.client.post.assert_called_once_with(
                "/api/dvr/entry/filemoved",
                data={"src": str(source), "dst": str(first_match)},
                timeout=30,
            )

    def test_dry_run_finds_file_without_updating_tvheadend(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "recordings"
            root.mkdir()
            match = root / "episode.ts"
            match.touch()
            repair = self._repair_for(base / "missing" / "episode.ts")

            result = repair.repair([root], dry_run=True)

            self.assertEqual(result.found, 1)
            self.assertEqual(result.updated, 0)
            repair.client.post.assert_not_called()

    def test_existing_source_path_is_re_registered(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_root = base / "old"
            new_root = base / "new"
            old_root.mkdir()
            new_root.mkdir()
            old_path = old_root / "episode.ts"
            new_path = new_root / "episode.ts"
            old_path.touch()
            new_path.touch()
            repair = self._repair_for(old_path)

            result = repair.repair([old_root, new_root])

            self.assertEqual(result.updated, 1)
            repair.client.post.assert_called_once_with(
                "/api/dvr/entry/filemoved",
                data={"src": str(old_path), "dst": str(old_path)},
                timeout=30,
            )

    def test_intentionally_removed_recording_is_not_repaired(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            match = base / "episode.ts"
            match.touch()
            repair = self._repair_for(base / "missing" / "episode.ts", fileremoved=True)

            result = repair.repair([base])

            self.assertEqual(result.intentionally_removed, 1)
            self.assertEqual(result.checked, 0)
            repair.client.post.assert_not_called()

    def test_removed_entry_without_file_missing_status_is_ignored(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            match = base / "episode.ts"
            match.touch()
            repair = self._repair_for(
                base / "missing" / "episode.ts",
                status="Completed OK",
            )

            result = repair.repair([base])

            self.assertEqual(result.other_removed, 1)
            self.assertEqual(result.checked, 0)
            repair.client.post.assert_not_called()

    @staticmethod
    def _repair_for(
        source: Path,
        fileremoved: bool = False,
        status: str = "File missing",
    ) -> TVHeadendMovedRecordingRepair:
        repair = TVHeadendMovedRecordingRepair({"url": "http://tvh"})
        repair.client = Mock()
        removed = Mock()
        removed.json.return_value = {
            "entries": [
                {
                    "files": [{"filename": str(source)}],
                    "fileremoved": fileremoved,
                    "status": status,
                }
            ]
        }
        repair.client.get.return_value = removed
        repair.client.post.return_value = Mock()
        return repair


if __name__ == "__main__":
    unittest.main()
