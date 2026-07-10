from __future__ import annotations

import json
import subprocess
from pathlib import Path

from config import is_verbose
from models import EncodingProfile, MediaInfo


def _stderr(config: dict):
    return None if is_verbose(config) else subprocess.DEVNULL


def ffprobe_json(path: Path, config: dict) -> dict:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        text=True,
        stderr=_stderr(config),
    )
    return json.loads(out)


def duration_seconds(path: Path, config: dict | None = None) -> int:
    cfg = config or {}

    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
            stderr=_stderr(cfg),
        ).strip()

        if out and out != "N/A":
            return round(float(out))

    except Exception:
        pass

    return 0


def determine_profile(height: int, profiles: dict) -> EncodingProfile:
    best_name = None
    best_cfg = None

    for name, cfg in profiles.items():
        if height >= int(cfg["min_height"]):
            if best_cfg is None or int(cfg["min_height"]) > int(best_cfg["min_height"]):
                best_name = name
                best_cfg = cfg

    if best_name is None or best_cfg is None:
        raise RuntimeError("No encoding profile matches")

    return EncodingProfile(
        name=best_name,
        preset=best_cfg["preset"],
        crf=int(best_cfg["crf"]),
        qsv_global_quality=int(best_cfg["qsv_global_quality"]),
        vaapi_qp=int(best_cfg["vaapi_qp"]),
    )


def select_audio(streams: list[dict]) -> tuple[int, str, str, str]:
    best = None
    best_prio = 999

    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue

        index = int(stream["index"])
        codec = stream.get("codec_name", "")
        language = stream.get("tags", {}).get("language", "")
        priority = 999
        reason = ""

        if language == "deu" and codec == "ac3":
            priority, reason = 1, "German AC3"
        elif language == "deu" and codec == "aac":
            priority, reason = 2, "German AAC"
        elif language == "deu" and codec == "mp2":
            priority, reason = 3, "German MP2"
        elif codec == "ac3":
            priority, reason = 4, "First AC3"
        elif codec == "aac":
            priority, reason = 5, "First AAC"
        elif codec == "mp2":
            priority, reason = 6, "First MP2"

        if priority < best_prio:
            best_prio = priority
            best = (index, codec, language, reason)

    if best is None:
        raise RuntimeError("No suitable audio stream found")

    return best


def media_info(path: Path, config: dict) -> MediaInfo:
    data = ffprobe_json(path, config)
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)

    if video is None:
        raise RuntimeError(f"No video stream found in {path}")

    audio_index, audio_codec, audio_language, audio_reason = select_audio(streams)
    height = int(video.get("height", 0))
    video_codec = video.get("codec_name", "")
    profile = determine_profile(height, config["profiles"])

    return MediaInfo(
        duration_seconds=duration_seconds(path, config),
        video_codec=video_codec,
        width=int(video.get("width", 0)),
        height=height,
        audio_stream_index=audio_index,
        audio_codec=audio_codec,
        audio_language=audio_language,
        audio_reason=audio_reason,
        video_copy=bool(config["encoder"].get("copy_hevc", True) and video_codec == "hevc"),
        audio_copy=audio_codec == "aac",
        profile=profile,
    )
