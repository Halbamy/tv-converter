from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from glob import escape
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from event_logger import logger
from models import ConvertedRecording, Recording
from tvheadend_client import TVHeadendClient


@dataclass
class MovedRecordingRepairResult:
    checked: int = 0
    missing: int = 0
    found: int = 0
    updated: int = 0
    not_found: int = 0
    without_filename: int = 0
    intentionally_removed: int = 0
    other_removed: int = 0
    errors: int = 0


class TVHeadendMovedRecordingRepair:
    def __init__(self, config: dict):
        self.client = TVHeadendClient(config)

    def repair(
        self,
        search_directories: list[Path],
        dry_run: bool = False,
    ) -> MovedRecordingRepairResult:
        directories = self._usable_directories(search_directories)
        result = MovedRecordingRepairResult()

        for entry in self._entries("/api/dvr/entry/grid_removed"):
            if bool(entry.get("fileremoved", entry.get("file_removed", False))):
                result.intentionally_removed += 1
                continue

            if str(entry.get("status", "")).strip().casefold() != "file missing":
                result.other_removed += 1
                continue

            filename = self._filename(entry)

            if not filename:
                result.without_filename += 1
                continue

            result.checked += 1
            source = Path(filename)
            result.missing += 1
            destination = self._find_first(source.name, directories, source)

            if destination is None:
                result.not_found += 1
                logger.warning("Moved TVHeadend recording not found: %s", source)
                continue

            result.found += 1

            if dry_run:
                logger.info(
                    "Would update TVHeadend recording path: %s -> %s",
                    source,
                    destination,
                )
                continue

            try:
                update = self.client.post(
                    "/api/dvr/entry/filemoved",
                    data={"src": str(source), "dst": str(destination)},
                    timeout=30,
                )
                update.raise_for_status()
            except Exception as exc:
                result.errors += 1
                logger.error(
                    "Failed to update TVHeadend recording path %s -> %s: %s",
                    source,
                    destination,
                    exc,
                )
                continue

            result.updated += 1
            logger.info(
                "Updated TVHeadend recording path: %s -> %s",
                source,
                destination,
            )

        return result

    def _entries(self, path: str) -> list[dict]:
        response = self.client.get(
            path,
            params={"limit": 999999, "sort": "start", "dir": "ASC"},
            timeout=30,
        )
        response.raise_for_status()
        return list(response.json().get("entries", []))

    def _usable_directories(self, directories: list[Path]) -> list[Path]:
        usable = []
        seen = set()

        for directory in directories:
            directory = directory.expanduser()
            key = str(directory.resolve())

            if key in seen:
                continue

            seen.add(key)

            if not directory.is_dir():
                logger.warning("Search directory does not exist or is not a directory: %s", directory)
                continue

            usable.append(directory)

        return usable

    @staticmethod
    def _find_first(
        filename: str,
        directories: list[Path],
        source: Path,
    ) -> Path | None:
        source = source.resolve()

        for directory in directories:
            for candidate in directory.rglob(escape(filename)):
                if candidate.is_file() and candidate.resolve() != source:
                    return candidate

        return None

    @staticmethod
    def _filename(entry: dict) -> str:
        if entry.get("filename"):
            return str(entry["filename"])

        files = entry.get("files") or []

        if files and isinstance(files[0], dict):
            return str(files[0].get("filename") or "")

        return ""


class TVHeadendStateMonitor:
    def __init__(self, config: dict, poll_interval: int = 300):
        self.config = config or {}
        self.poll_interval = poll_interval
        self.client = TVHeadendClient(config)

    def wait_until_not_busy(
        self,
        on_busy: Callable[[int, int], None] | None = None,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        waited = False

        while True:
            recordings, subscriptions = self.busy_counts()

            if recordings == 0 and subscriptions == 0:
                if waited and on_ready is not None:
                    on_ready()
                return

            waited = True

            if on_busy is not None:
                on_busy(recordings, subscriptions)

            logger.info(
                "TVHeadend busy (recordings=%s, subscriptions=%s), waiting %s seconds.",
                recordings,
                subscriptions,
                self.poll_interval,
            )
            time.sleep(self.poll_interval)

    def busy_counts(self) -> tuple[int, int]:
        recordings = self._active_recording_count()
        subscriptions = self._active_subscription_count()
        return recordings, subscriptions

    def _active_recording_count(self) -> int:
        data = self._get_json(
            "/api/dvr/entry/grid_upcoming",
            {"limit": 999999},
        )
        count = 0

        for entry in data.get("entries", []):
            status = str(entry.get("status", "")).strip().lower()
            sched_status = str(entry.get("sched_status", "")).strip().lower()

            if status == "recording" or sched_status == "recording":
                count += 1

        return count

    def _active_subscription_count(self) -> int:
        data = self._get_json("/api/status/subscriptions", {})
        return len(data.get("entries", []))

    def _get_json(self, path: str, params: dict) -> dict:
        try:
            response = self.client.get(path, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("TVHeadend state check failed for %s: %s", path, exc)
            return {"entries": [{"busy": True}]}


class TVHeadendImporter:
    def __init__(self, config: dict, source_config: dict | None = None):
        self.config = config or {}
        self.source_config = source_config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.client = TVHeadendClient(config)

    def channel_name(self, recording: Recording) -> str:
        mapping = self.config.get("channel_mapping", {}) or {}
        return mapping.get(recording.channel, recording.channel)

    def build_dict(self, recording: Recording, converted: ConvertedRecording) -> dict:
        start = int(recording.starttime.timestamp())
        stop = start + converted.duration_seconds

        return {
            "enabled": True,
            "start": start,
            "stop": stop,
            "channelname": self.channel_name(recording),
            "title": {"ger": recording.title, "eng": recording.title},
            "subtitle": {"ger": recording.subtitle, "eng": recording.subtitle},
            "description": {"ger": recording.description, "eng": recording.description},
            "comment": self.config.get("comment", "imported by tv-converter"),
            "files": [{"filename": str(converted.output_file)}],
        }

    def build_json(self, recording: Recording, converted: ConvertedRecording) -> str:
        return json.dumps(self.build_dict(recording, converted), indent=2, ensure_ascii=False)

    def import_recording(self, recording: Recording, converted: ConvertedRecording) -> bool:
        if getattr(recording, "deletepending", False):
            logger.info(
                "Refusing TVHeadend import for deletepending recording: %s",
                recording.title,
            )
            return False

        if not self.enabled:
            return True

        if recording.source == "tvheadend" and self._same_instance():
            return self._file_moved(recording, converted)

        response = self.client.post(
            "/api/dvr/entry/create",
            data={"conf": json.dumps(self.build_dict(recording, converted), ensure_ascii=False)},
            timeout=30,
        )
        response.raise_for_status()
        logger.info("Imported into TVHeadend: %s", converted.output_file.name)
        return True

    def _file_moved(self, recording: Recording, converted: ConvertedRecording) -> bool:
        response = self.client.post(
            "/api/dvr/entry/filemoved",
            data={"src": str(recording.filename), "dst": str(converted.output_file)},
            timeout=30,
        )
        response.raise_for_status()
        logger.info(
            "Updated TVHeadend recording path: %s -> %s",
            recording.filename,
            converted.output_file,
        )
        return True

    def _same_instance(self) -> bool:
        source_url = self.source_config.get("url")
        destination_url = self.config.get("url")

        if not source_url or not destination_url:
            return False

        return self._normalize_url(source_url) == self._normalize_url(destination_url)

    @staticmethod
    def _normalize_url(url: str) -> str:
        parsed = urlsplit(url.strip())
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        port = parsed.port

        if port is None:
            port = 443 if scheme == "https" else 80

        return urlunsplit((scheme, f"{hostname}:{port}", parsed.path.rstrip("/"), "", ""))


@dataclass
class RecordingRenameResult:
    checked: int = 0
    renamed: int = 0
    errors: int = 0
    skipped: int = 0


class TVHeadendRecordingRenamer:
    """Rename completed TVHeadend recordings to the current naming schema."""

    def __init__(self, config: dict):
        self.config = config or {}
        self.client = TVHeadendClient(config)

    def rename_recordings(
        self,
        config: dict,
        output_directory: Path,
        uuid: str | None = None,
        dry_run: bool = False,
    ) -> RecordingRenameResult:
        """Rename all completed TVHeadend recordings to match the current naming schema.
        
        Args:
            config: Full application config
            output_directory: Output directory path
            uuid: Optional UUID to rename only a specific recording
            dry_run: If True, don't actually rename files
        """
        from encoder import Encoder

        result = RecordingRenameResult()
        encoder = Encoder(config)
        
        # Get all finished recordings from TVHeadend
        try:
            entries = self._get_finished_entries()
        except Exception as exc:
            logger.error("Failed to fetch TVHeadend recordings: %s", exc)
            return result

        # Filter by UUID if provided
        if uuid:
            entries = [e for e in entries if str(e.get("uuid", e.get("id", ""))).strip() == uuid.strip()]
            if not entries:
                logger.warning("No TVHeadend recording found with UUID: %s", uuid)
                return result

        for entry in entries:
            result.checked += 1
            filename = self._filename(entry)

            if not filename:
                result.skipped += 1
                continue

            old_path = Path(filename)

            if not old_path.exists():
                logger.warning("Recording file does not exist: %s", old_path)
                result.skipped += 1
                continue

            # Try to reconstruct the Recording object from TVHeadend entry
            try:
                recording = self._entry_to_recording(entry)
            except Exception as exc:
                logger.warning("Could not parse TVHeadend entry: %s", exc)
                result.skipped += 1
                continue

            # Generate the expected new filename
            try:
                new_path = encoder.output_filename(recording)
            except Exception as exc:
                logger.error("Failed to generate new filename for %s: %s", old_path.name, exc)
                result.errors += 1
                continue

            # Check if filename already matches the new format
            if old_path.resolve() == new_path.resolve():
                logger.debug("Already using new naming schema: %s", old_path.name)
                result.skipped += 1
                continue

            if dry_run:
                logger.info("Would rename: %s -> %s", old_path.name, new_path.name)
                result.renamed += 1
                continue

            # Perform the rename
            try:
                old_path.rename(new_path)
                logger.info("Renamed recording: %s -> %s", old_path.name, new_path.name)

                # Notify TVHeadend about the file move
                try:
                    response = self.client.post(
                        "/api/dvr/entry/filemoved",
                        data={"src": str(old_path), "dst": str(new_path)},
                        timeout=30,
                    )
                    response.raise_for_status()
                    logger.info("Notified TVHeadend about renamed recording: %s", new_path.name)
                except Exception as exc:
                    logger.warning("Could not notify TVHeadend about renamed file: %s", exc)

                result.renamed += 1
            except Exception as exc:
                logger.error("Failed to rename recording %s -> %s: %s", old_path, new_path, exc)
                result.errors += 1

        return result

    def _get_finished_entries(self) -> list[dict]:
        """Fetch all finished/completed recordings from TVHeadend."""
        response = self.client.get(
            "/api/dvr/entry/grid_finished",
            params={"limit": 999999, "sort": "start", "dir": "ASC"},
            timeout=30,
        )
        response.raise_for_status()
        return list(response.json().get("entries", []))

    @staticmethod
    def _filename(entry: dict) -> str:
        """Extract filename from TVHeadend entry."""
        if entry.get("filename"):
            return str(entry["filename"])

        files = entry.get("files") or []

        if files and isinstance(files[0], dict):
            return str(files[0].get("filename") or "")

        return ""

    @staticmethod
    def _entry_to_recording(entry: dict) -> Recording:
        """Convert a TVHeadend entry dict to a Recording object."""
        from datetime import datetime

        filename = TVHeadendRecordingRenamer._filename(entry)
        
        return Recording(
            source="tvheadend",
            recording_id=str(entry.get("uuid", entry.get("id", "unknown"))),
            title=str(entry.get("title", "Unknown")),
            subtitle=str(entry.get("subtitle", "")),
            description=str(entry.get("description", "")),
            channel=str(entry.get("channelname", "")),
            starttime=datetime.fromtimestamp(int(entry.get("start", 0))),
            endtime=datetime.fromtimestamp(int(entry.get("stop", 0))),
            filename=Path(filename),
            duration_minutes=int((int(entry.get("stop", 0)) - int(entry.get("start", 0))) / 60),
            deletepending=bool(entry.get("fileremoved", False)),
        )
