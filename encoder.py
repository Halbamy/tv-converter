from __future__ import annotations

from pathlib import Path
import subprocess

from config import is_verbose, source_config
from ffprobe_utils import media_info
from filename_utils import build_output_filename
from models import EncodingPlan, MediaInfo, Recording, VERSION


class Encoder:
    def __init__(self, config: dict):
        self.config = config

    def _encoder_type(self) -> str:
        encoder = self.config["encoder"].get("type", "auto")
        return "sw" if encoder in {"software", "libx265"} else encoder

    def output_directory(self, recording: Recording) -> Path:
        output_dir = source_config(self.config)["output"]["directory"]

        if output_dir == "original":
            return recording.filename.parent

        return Path(output_dir)

    def output_filename(self, recording: Recording, suffix: str = ".mkv") -> Path:
        output_dir = self.output_directory(recording)
        output_dir.mkdir(parents=True, exist_ok=True)
        fallback = int(self.config.get("output", {}).get("description_fallback_chars", 25))
        return build_output_filename(recording, output_dir, fallback, suffix=suffix)

    def qsv_device(self) -> str:
        return self.config["encoder"].get("qsv", {}).get("device", "/dev/dri/renderD128")

    def qsv_filter(self) -> str:
        frames = int(self.config["encoder"].get("qsv", {}).get("extra_hw_frames", 10))
        return f"format=nv12,hwupload=extra_hw_frames={frames}"

    def vaapi_device(self) -> str:
        return self.config["encoder"].get("vaapi", {}).get("device", "/dev/dri/renderD128")

    def vaapi_filter(self) -> str:
        frames = int(self.config["encoder"].get("vaapi", {}).get("extra_hw_frames", 10))
        return f"format=nv12,hwupload=extra_hw_frames={frames}"

    def vaapi_rc_mode(self) -> str:
        return self.config["encoder"].get("vaapi", {}).get("rc_mode", "ICQ")

    def qsv_available(self) -> bool:
        try:
            subprocess.check_call(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-qsv_device",
                    self.qsv_device(),
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=128x128:rate=1",
                    "-frames:v",
                    "1",
                    "-vf",
                    self.qsv_filter(),
                    "-c:v",
                    "hevc_qsv",
                    "-global_quality",
                    "24",
                    "-f",
                    "null",
                    "-",
                ],
                stdout=subprocess.DEVNULL,
                stderr=None if is_verbose(self.config) else subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    def vaapi_available(self) -> bool:
        try:
            subprocess.check_call(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-vaapi_device",
                    self.vaapi_device(),
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=128x128:rate=1",
                    "-frames:v",
                    "1",
                    "-vf",
                    self.vaapi_filter(),
                    "-c:v",
                    "hevc_vaapi",
                    "-f",
                    "null",
                    "-",
                ],
                stdout=subprocess.DEVNULL,
                stderr=None if is_verbose(self.config) else subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    def video_options(self, media: MediaInfo):
        if media.video_copy:
            return ["-c:v", "copy"], "copy"

        encoder = self._encoder_type()

        if encoder == "auto":
            if self.vaapi_available():
                encoder = "vaapi"
            elif self.qsv_available():
                encoder = "qsv"
            else:
                encoder = "sw"

        if encoder == "qsv":
            return (
                [
                    "-qsv_device",
                    self.qsv_device(),
                    "-vf",
                    self.qsv_filter(),
                    "-c:v",
                    "hevc_qsv",
                    "-global_quality",
                    str(media.profile.qsv_global_quality),
                ],
                "hevc_qsv",
            )

        if encoder == "vaapi":
            return (
                [
                    "-vaapi_device",
                    self.vaapi_device(),
                    "-vf",
                    self.vaapi_filter(),
                    "-c:v",
                    "hevc_vaapi",
                    "-rc_mode",
                    self.vaapi_rc_mode(),
                    "-qp",
                    str(media.profile.vaapi_qp),
                ],
                "hevc_vaapi",
            )

        return (
            ["-c:v", "libx265", "-preset", media.profile.preset, "-crf", str(media.profile.crf)],
            "libx265",
        )

    def audio_options(self, media: MediaInfo) -> list[str]:
        if media.audio_copy:
            return ["-c:a", "copy"]

        return [
            "-c:a",
            "aac",
            "-q:a",
            str(self.config["encoder"].get("audio_quality", "2")),
            "-af",
            "aresample=async=1",
        ]

    def metadata_options(
        self,
        recording: Recording,
        media: MediaInfo,
        encoder_name: str,
    ) -> list[str]:
        return [
            "-metadata",
            f"title={recording.title}",
            "-metadata",
            f"summary={recording.subtitle}",
            "-metadata",
            f"description={recording.description}",
            "-metadata",
            f"network={recording.channel}",
            "-metadata",
            f"date={recording.starttime:%Y-%m-%d}",
            "-metadata",
            "comment=Imported by tv-converter",
            "-metadata",
            f"encoded_by=tv-converter {VERSION}",
            "-metadata",
            f"encoder={encoder_name}",
            "-metadata",
            f"profile={media.profile.name}",
        ]

    def build_none_plan(self, recording: Recording, media: MediaInfo) -> EncodingPlan:
        output = self.output_filename(recording, suffix=".mkv")
        temp = output.with_suffix(output.suffix + ".part")
        encoder_name = "copy"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "warning",
            "-fflags",
            "+genpts+discardcorrupt",
            "-err_detect",
            "ignore_err",
            "-i",
            str(recording.filename),
            "-map",
            "0:v:0",
            "-map",
            f"0:{media.audio_stream_index}",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-metadata:s:a:0",
            "language=deu",
            *self.metadata_options(recording, media, encoder_name),
            "-avoid_negative_ts",
            "make_zero",
            "-progress",
            "pipe:1",
            "-f",
            "matroska",
            str(temp),
        ]
        return EncodingPlan(command, media, output, temp, encoder_name)

    def build_plan(self, recording: Recording) -> EncodingPlan:
        media = media_info(recording.filename, self.config)

        if self._encoder_type() == "none":
            return self.build_none_plan(recording, media)

        output = self.output_filename(recording, suffix=".mkv")
        temp = output.with_suffix(output.suffix + ".part")
        video_opts, encoder_name = self.video_options(media)
        audio_opts = self.audio_options(media)

        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "warning",
            "-fflags",
            "+genpts+discardcorrupt",
            "-err_detect",
            "ignore_err",
            "-i",
            str(recording.filename),
            "-map",
            "0:v:0",
            "-map",
            f"0:{media.audio_stream_index}",
            *video_opts,
            "-max_muxing_queue_size",
            "4096",
            *audio_opts,
            "-metadata:s:a:0",
            "language=deu",
            *self.metadata_options(recording, media, encoder_name),
            "-avoid_negative_ts",
            "make_zero",
            "-progress",
            "pipe:1",
            "-f",
            "matroska",
            str(temp),
        ]

        return EncodingPlan(command, media, output, temp, encoder_name)
