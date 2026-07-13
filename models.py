from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


VERSION = "2.3.2"


@dataclass(frozen=True)
class Recording:
    source: str
    recording_id: str
    title: str
    subtitle: str
    description: str
    channel: str
    starttime: datetime
    endtime: datetime
    filename: Path
    duration_minutes: int
    deletepending: bool = False


@dataclass(frozen=True)
class EncodingProfile:
    name: str
    preset: str
    crf: int
    qsv_global_quality: int
    vaapi_qp: int


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: int
    video_codec: str
    width: int
    height: int
    audio_stream_index: int
    audio_codec: str
    audio_language: str
    audio_reason: str
    video_copy: bool
    audio_copy: bool
    profile: EncodingProfile


@dataclass(frozen=True)
class EncodingPlan:
    command: list[str]
    media: MediaInfo | None
    output_file: Path
    temp_file: Path | None
    encoder_name: str
    action: str = "transcode"
    message: str = ""


@dataclass(frozen=True)
class ConvertedRecording:
    source: Recording
    output_file: Path
    duration_seconds: int
    input_size: int
    output_size: int
    encoder_name: str
    profile_name: str


@dataclass
class Progress:
    speed: float = 0.0
    out_time_us: int = 0

    @property
    def out_time_seconds(self) -> float:
        return self.out_time_us / 1_000_000

    def percent_value(self, duration_seconds: int) -> int | None:
        if duration_seconds <= 0:
            return None
        if self.out_time_seconds <= 0:
            return 0
        return min(100, int(self.out_time_seconds * 100 / duration_seconds))

    def percent(self, duration_seconds: int) -> str:
        value = self.percent_value(duration_seconds)
        return "--" if value is None else f"{value}%"

    def eta(self, duration_seconds: int) -> str:
        if duration_seconds <= 0 or self.out_time_seconds <= 0 or self.speed <= 0:
            return "--:--"

        remaining = max(0, (duration_seconds - self.out_time_seconds) / self.speed)
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)

        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


@dataclass
class PVState:
    power: str = "----"
    state: str = "RUNNING"
    last_message: float = 0.0
    mqtt_alive: bool = True
