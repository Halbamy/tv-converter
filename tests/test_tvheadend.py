from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from models import ConvertedRecording, Recording
from tvheadend import (
    TVHeadendImporter,
    TVHeadendMovedRecordingRepair,
    TVHeadendStateMonitor,
)


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


class TVHeadendMovedRecordingRepairTest(unittest.TestCase):
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

    def test_existing_recording_path_is_not_changed(self):
        with TemporaryDirectory() as tmp:
            existing = Path(tmp) / "episode.ts"
            existing.touch()
            repair = self._repair_for(existing)

            result = repair.repair([Path(tmp)])

            self.assertEqual(result.checked, 1)
            self.assertEqual(result.missing, 0)
            repair.client.post.assert_not_called()

    @staticmethod
    def _repair_for(source: Path) -> TVHeadendMovedRecordingRepair:
        repair = TVHeadendMovedRecordingRepair({"url": "http://tvh"})
        repair.client = Mock()
        listing = Mock()
        listing.json.return_value = {"entries": [{"files": [{"filename": str(source)}]}]}
        repair.client.get.return_value = listing
        repair.client.post.return_value = Mock()
        return repair


if __name__ == "__main__":
    unittest.main()
