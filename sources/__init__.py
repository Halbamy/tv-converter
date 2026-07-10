from __future__ import annotations

from sources.base import RecordingSource
from sources.mythtv import MythTVSource
from sources.tvheadend import TVHeadendSource


def create_source(config: dict) -> RecordingSource:
    source_cfg = config["source"]
    source_type = source_cfg.get("type", "mythtv")

    if source_type == "mythtv":
        return MythTVSource(source_cfg["mythtv"])

    if source_type == "tvheadend":
        return TVHeadendSource(source_cfg["tvheadend"])

    raise ValueError(f"Unsupported source type: {source_type}")
