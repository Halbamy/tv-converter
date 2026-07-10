from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from models import Recording
from sources.base import RecordingSource
from tvheadend_client import TVHeadendClient


class TVHeadendSource(RecordingSource):
    def __init__(self, config: dict):
        self.config = config
        self.client = TVHeadendClient(config)

    def get_recordings(self) -> list[Recording]:
        response = self.client.get(
            "/api/dvr/entry/grid_finished",
            params={"limit": 999999, "sort": "start", "dir": "ASC"},
            timeout=30,
        )
        response.raise_for_status()
        recordings: list[Recording] = []

        for entry in response.json().get("entries", []):
            if entry.get("status") and entry.get("status") != "Completed OK":
                continue

            filename = self._filename(entry)
            if not filename:
                continue

            start_ts = int(entry.get("start", 0) or 0)
            stop_ts = int(entry.get("stop", entry.get("end", 0)) or 0)

            if start_ts <= 0:
                continue

            starttime = datetime.fromtimestamp(start_ts)
            endtime = datetime.fromtimestamp(stop_ts) if stop_ts > start_ts else starttime
            duration = max(0, int((endtime - starttime).total_seconds() // 60))

            recordings.append(
                Recording(
                    source="tvheadend",
                    recording_id=str(entry.get("uuid") or entry.get("id") or filename),
                    title=self._text(entry.get("disp_title") or entry.get("title")),
                    subtitle=self._text(entry.get("disp_subtitle") or entry.get("subtitle")),
                    description=self._text(entry.get("description") or entry.get("disp_description")),
                    channel=str(entry.get("channelname") or entry.get("channel") or ""),
                    starttime=starttime,
                    endtime=endtime,
                    filename=Path(filename),
                    duration_minutes=duration,
                    deletepending=False,
                )
            )

        return recordings

    def _filename(self, entry: dict[str, Any]) -> str:
        if entry.get("filename"):
            return str(entry["filename"])

        files = entry.get("files") or []

        if files and isinstance(files[0], dict):
            return str(files[0].get("filename") or "")

        return ""

    def _text(self, value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("ger") or value.get("eng") or next(iter(value.values()), ""))

        return str(value or "")
