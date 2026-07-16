from __future__ import annotations

import re
from pathlib import Path
import subprocess

from config import destination_config, is_verbose
from event_logger import logger
from ffprobe_utils import inspect_existing_output, media_info
from filename_utils import build_output_filename
from models import EncodingPlan, MediaInfo, Recording, VERSION
from tvheadend_client import TVHeadendClient


class Encoder:
    def __init__(self, config: dict):
        self.config = config

    def _encoder_type(self) -> str:
        encoder = self.config["encoder"].get("type", "auto")
        return "sw" if encoder in {"software", "libx265"} else encoder

    def output_directory(self, recording: Recording) -> Path:
        output = destination_config(self.config)["output"]

        if output.get("mode") == "original":
            return recording.filename.parent

        return Path(output["directory"])

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

    def _matches_old_format(self, filename: str) -> bool:
        """Check if filename matches old format: YYYY-MM-DD_HH_MM_SS_..."""
        # Pattern: starts with YYYY-MM-DD_HH_MM_SS_
        pattern = r"^\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}_"
        return bool(re.match(pattern, filename))

    def _rename_to_new_format(self, old_path: Path, new_path: Path) -> bool:
        """Rename file from old format to new format and notify TVHeadend."""
        if not old_path.exists():
            return False

        if old_path.resolve() == new_path.resolve():
            # Already has correct path
            return False

        try:
            old_path.rename(new_path)
            logger.info("Renamed recording: %s -> %s", old_path.name, new_path.name)

            # Notify TVHeadend about the file move
            try:
                tvheadend = self.config.get("tvheadend", {})
                if tvheadend.get("enabled", False) and tvheadend.get("url"):
                    client = TVHeadendClient(tvheadend)
                    response = client.post(
                        "/api/dvr/entry/filemoved",
                        data={"src": str(old_path), "dst": str(new_path)},
                        timeout=30,
                    )
                    response.raise_for_status()
                    logger.info("Notified TVHeadend about renamed recording: %s", new_path.name)
            except Exception as exc:
                logger.warning("Could not notify TVHeadend about renamed file: %s", exc)

            return True
        except Exception as exc:
            logger.error("Failed to rename recording: %s -> %s (%s)", old_path, new_path, exc)
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

    def build_metadata_remux_plan(
        self,
        recording: Recording,
        media: MediaInfo,
        output: Path,
    ) -> EncodingPlan:
        temp = output.with_suffix(output.suffix + ".part")
        encoder_name = "copy"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "warning",
            "-i",
            str(output),
            "-map",
            "0",
            "-map_metadata",
            "0",
            "-c",
            "copy",
            *self.metadata_options(recording, media, encoder_name),
            "-progress",
            "pipe:1",
            "-f",
            "matroska",
            str(temp),
        ]
        return EncodingPlan(
            command,
            media,
            output,
            temp,
            encoder_name,
            action="metadata_remux",
        )

    def build_plan(self, recording: Recording) -> EncodingPlan:
        output = self.output_filename(recording, suffix=".mkv")
        existing_media = None

        if output.exists():
            try:
                existing_media, processed = inspect_existing_output(output, self.config)
            except Exception as exc:
                return EncodingPlan(
                    [],
                    None,
                    output,
                    None,
                    "unknown",
                    action="manual_review",
                    message=str(exc),
                )

            if processed:
                return EncodingPlan(
                    [],
                    existing_media,
                    output,
                    None,
                    "existing",
                    action="skip_processed",
                )

            if existing_media.video_codec == "hevc":
                return self.build_metadata_remux_plan(recording, existing_media, output)

        if recording.filename.resolve() == output.resolve() and existing_media is not None:
            media = existing_media
        else:
            media = media_info(recording.filename, self.config)

        if self._encoder_type() == "none":
            return self.build_none_plan(recording, media)

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
