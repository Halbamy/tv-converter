from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from event_logger import logger
from models import ConvertedRecording, Recording
from tvheadend_client import TVHeadendClient


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
