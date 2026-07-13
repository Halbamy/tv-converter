from __future__ import annotations

import threading
import time

from encoder import Encoder
from event_logger import logger
from ffmpeg_runner import FFmpegRunner
from ffprobe_utils import duration_seconds
from models import ConvertedRecording, Progress, Recording
from mqtt_controller import MQTTController
from permissions import PermissionManager
from status import StatusDisplay


class Converter:
    def __init__(self, config: dict, mqtt: MQTTController):
        self.config = config
        self.encoder = Encoder(config)
        self.runner = FFmpegRunner(config)
        self.status = StatusDisplay()
        self.mqtt = mqtt
        self.permissions = PermissionManager(config)
        self.current_recording: Recording | None = None
        self.current_plan = None
        self.current_progress: Progress | None = None
        self.file_index = 0
        self.file_count = 0
        self.last_percent: int | None = None
        self.last_eta = "--:--"
        self._status_stop = threading.Event()
        self._status_thread: threading.Thread | None = None

    def prepare(self, recording: Recording):
        return self.encoder.build_plan(recording)

    def convert(
        self,
        recording: Recording,
        file_index: int,
        file_count: int,
        plan=None,
    ) -> ConvertedRecording | None:
        self.current_recording = recording
        self.file_index = file_index
        self.file_count = file_count
        self.current_progress = Progress()
        self.last_percent = None
        self.last_eta = "--:--"
        self._status_stop.clear()

        plan = plan or self.encoder.build_plan(recording)
        self.current_plan = plan

        if plan.action == "skip_processed":
            logger.info("Already processed by tv-converter, skipping: %s", plan.output_file)
            return None

        if plan.action == "manual_review":
            logger.warning(
                "Existing MKV could not be analyzed and was skipped. "
                "Please check it manually: %s (%s)",
                plan.output_file,
                plan.message or "ffprobe failed",
            )
            return None

        if plan.temp_file and plan.temp_file.exists():
            raise RuntimeError(f"Unfinished conversion exists. Remove manually:\n  {plan.temp_file}")

        assert plan.media is not None

        if plan.action == "metadata_remux":
            logger.info(
                "Legacy HEVC recording without tv-converter metadata detected; "
                "adding metadata only: %s",
                plan.output_file.name,
            )
        else:
            logger.info(
                "Starting conversion: %s (encoder=%s, profile=%s)",
                plan.output_file.name,
                plan.encoder_name,
                plan.media.profile.name,
            )
        self._start_status_thread()

        try:
            rc = self.runner.run(plan.command, self._on_progress)
        finally:
            self._stop_status_thread()
            self.status.finish()

        if rc != 0:
            if self.mqtt.control.stop_requested and plan.temp_file and plan.temp_file.exists():
                plan.temp_file.unlink()
                raise RuntimeError("Stopped by user. Temporary file was removed.")
            raise RuntimeError(self._ffmpeg_error_message(recording, plan, rc))

        assert plan.temp_file is not None
        plan.temp_file.replace(plan.output_file)
        self.permissions.file(plan.output_file)
        if plan.action == "metadata_remux":
            logger.info("Finished metadata update: %s", plan.output_file.name)
        else:
            logger.info("Finished conversion: %s", plan.output_file.name)

        return self._converted_recording(recording, plan)

    def _converted_recording(self, recording: Recording, plan) -> ConvertedRecording:
        return ConvertedRecording(
            source=recording,
            output_file=plan.output_file,
            duration_seconds=(
                duration_seconds(plan.output_file, self.config)
                or (plan.media.duration_seconds if plan.media else 0)
            ),
            input_size=recording.filename.stat().st_size,
            output_size=plan.output_file.stat().st_size,
            encoder_name=plan.encoder_name,
            profile_name=plan.media.profile.name if plan.media else "unknown",
        )

    def _ffmpeg_error_message(self, recording: Recording, plan, rc: int) -> str:
        stderr = self.runner.last_stderr.strip() or "(no stderr captured)"
        command = " ".join(plan.command)

        return (
            "\n------------------------------------------------------------\n"
            "FFmpeg failed\n"
            "------------------------------------------------------------\n"
            f"Exit code : {rc}\n"
            f"Encoder   : {plan.encoder_name}\n"
            f"Input     : {recording.filename}\n"
            f"Temp file : {plan.temp_file}\n"
            f"Output    : {plan.output_file}\n\n"
            f"FFmpeg command:\n{command}\n\n"
            "FFmpeg stderr:\n"
            "------------------------------------------------------------\n"
            f"{stderr}\n"
            "------------------------------------------------------------"
        )

    def _on_progress(self, progress: Progress, finished: bool) -> None:
        if finished:
            return

        self.current_progress = progress
        self._render_status()

    def _render_status(self) -> None:
        if self.current_recording is None or self.current_plan is None or self.current_progress is None:
            return

        progress = self.current_progress
        percent_value = progress.percent_value(self.current_plan.media.duration_seconds)

        if percent_value != self.last_percent:
            self.last_percent = percent_value
            self.last_eta = progress.eta(self.current_plan.media.duration_seconds)

        percent_text = progress.percent(self.current_plan.media.duration_seconds)

        self.status.update(
            file_index=self.file_index,
            file_count=self.file_count,
            power=self.mqtt.state.power,
            state=self.mqtt.state.state,
            filename=self.current_plan.output_file.name,
            percent=percent_text,
            speed=f"{progress.speed:.2f}x",
            eta=self.last_eta,
        )
        self.mqtt.publish_runtime_status(
            state=self.mqtt.state.state.lower(),
            source=self.current_recording.source,
            encoder=self.current_plan.encoder_name,
            current_file=self.current_plan.output_file.name,
            fullpath=str(self.current_plan.output_file),
            current_title=self.current_recording.title,
            progress=percent_value,
            eta=self.last_eta,
            queue={"current": self.file_index, "total": self.file_count},
        )

    def _start_status_thread(self) -> None:
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()

    def _stop_status_thread(self) -> None:
        self._status_stop.set()

        if self._status_thread is not None:
            self._status_thread.join(timeout=2)
            self._status_thread = None

    def _status_loop(self) -> None:
        while not self._status_stop.is_set():
            self._render_status()
            time.sleep(3)
