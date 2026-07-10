from __future__ import annotations

import json
import time

from event_logger import logger
from models import ConvertedRecording, Recording
from tvheadend_client import TVHeadendClient


class TVHeadendIdleMonitor:
    def __init__(self, config: dict):
        self.config = config or {}
        idle = self.config.get("idle", {})
        self.enabled = bool(idle.get("enabled", True))
        self.poll_interval = int(idle.get("poll_interval", 300))
        self.client = TVHeadendClient(config)

    def wait_until_idle(self) -> None:
        if not self.enabled:
            return

        while not self.is_idle():
            logger.info("TVHeadend is busy, waiting %s seconds.", self.poll_interval)
            time.sleep(self.poll_interval)

    def is_idle(self) -> bool:
        return not self.has_active_recordings() and not self.has_active_subscriptions()

    def has_active_recordings(self) -> bool:
        data = self._get_json("/api/dvr/entry/grid_upcoming", {"limit": 999999})

        for entry in data.get("entries", []):
            status = str(entry.get("status", "")).lower()
            sched_status = str(entry.get("sched_status", "")).lower()

            if "recording" in status or "recording" in sched_status:
                return True

            if entry.get("filename") and entry.get("start_real") and not entry.get("stop_real"):
                return True

        return False

    def has_active_subscriptions(self) -> bool:
        data = self._get_json("/api/status/subscriptions", {})

        for entry in data.get("entries", []):
            service = str(entry.get("service", "")).lower()
            title = str(entry.get("title", "")).lower()

            if "dvr" in service or "dvr" in title:
                return True

            if entry.get("username") or entry.get("hostname"):
                return True

        return False

    def _get_json(self, path: str, params: dict) -> dict:
        try:
            response = self.client.get(path, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("TVHeadend idle check failed: %s", exc)
            return {"entries": [{"busy": True}]}


class TvheadendImporter:
    def __init__(self, config: dict):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
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

        response = self.client.post(
            "/api/dvr/entry/create",
            data={"conf": json.dumps(self.build_dict(recording, converted), ensure_ascii=False)},
            timeout=30,
        )
        response.raise_for_status()
        logger.info("Imported into TVHeadend: %s", converted.output_file.name)

        return True
