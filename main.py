#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path

from config import load_config, source_config
from converter import Converter
from event_logger import configure_logging, logger
from mqtt_controller import MQTTController, ServiceControl
from postprocessing import PlexPostprocessor
from recording_queue import RecordingQueue
from sources import create_source
from tvheadend import TVHeadendIdleMonitor, TvheadendImporter


def filter_recordings(recordings, cfg):
    selection = cfg.get("selection", {})
    min_minutes = int(selection.get("min_minutes", 0) or 0)
    title_contains = selection.get("title_contains")
    channel_contains = selection.get("channel_contains")
    limit = int(selection.get("limit", 0) or 0)
    result = []

    for recording in recordings:
        if min_minutes and recording.duration_minutes < min_minutes:
            continue
        if title_contains and title_contains.lower() not in recording.title.lower():
            continue
        if channel_contains and channel_contains.lower() not in recording.channel.lower():
            continue
        if not recording.filename.exists():
            continue
        result.append(recording)

    return result[:limit] if limit > 0 else result


class App:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.control = ServiceControl()
        self.queue = RecordingQueue()
        self.mqtt = MQTTController(self.config.get("mqtt", {}), lambda: None, self.control)
        self.converter: Converter | None = None
        self.tvheadend = TvheadendImporter(self.config.get("tvheadend", {}))
        self.idle = TVHeadendIdleMonitor(self.config.get("tvheadend", {}))
        self.plex = PlexPostprocessor(self.config.get("postprocessing", {}))

    def request_reload(self, signum=None, frame=None) -> None:
        logger.info("Reload requested.")
        self.control.reload_requested = True

    def reload(self) -> None:
        logger.info("Reloading configuration.")
        self.config = load_config(self.config_path)
        self.control.reload_requested = False
        self.tvheadend = TvheadendImporter(self.config.get("tvheadend", {}))
        self.idle = TVHeadendIdleMonitor(self.config.get("tvheadend", {}))
        self.plex = PlexPostprocessor(self.config.get("postprocessing", {}))

    def stop(self, signum=None, frame=None) -> None:
        self.control.stop_requested = True

        if self.converter is not None:
            self.converter.runner.terminate()

    def run(self, dry_run: bool, show_ffmpeg: bool, show_tvh_json: bool) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGHUP, self.request_reload)

        self.converter = Converter(self.config, self.mqtt)
        self.mqtt.process_getter = lambda: self.converter.runner.process
        self.mqtt.start()

        try:
            while not self.control.stop_requested:
                if self.control.reload_requested:
                    self.reload()

                if len(self.queue) == 0:
                    source = create_source(self.config)
                    recordings = filter_recordings(source.get_recordings(), self.config)
                    added = self.queue.add_new(recordings)
                    logger.info("%s new recording(s) found.", added)

                    if added == 0:
                        self.mqtt.publish_runtime_status(state="idle", progress=0, queue={"current": 0, "total": 0})
                        self._sleep_poll_interval()
                        continue

                self._process_queue(dry_run, show_ffmpeg, show_tvh_json)
        finally:
            self.mqtt.stop()

    def _process_queue(self, dry_run: bool, show_ffmpeg: bool, show_tvh_json: bool) -> None:
        total = len(self.queue)
        index = 0
        changed_files = False
        converted_for_delete = []

        while len(self.queue) > 0 and not self.control.stop_requested:
            index += 1
            recording = self.queue.pop()

            if recording is None:
                return

            if getattr(recording, "deletepending", False):
                logger.info(
                    "Skipping deletepending recording before processing: %s",
                    recording.title,
                )
                continue

            assert self.converter is not None
            plan = self.converter.prepare(recording)

            if dry_run:
                self._print_plan(recording, plan, index, total, show_ffmpeg, show_tvh_json)
                continue

            self.idle.wait_until_idle()

            try:
                converted = self.converter.convert(recording, index, total)
            except RuntimeError as exc:
                logger.error("%s", exc)
                self.control.stop_requested = True
                return

            self.idle.wait_until_idle()
            import_ok = self.tvheadend.import_recording(recording, converted)

            if not import_ok:
                logger.info(
                    "TVHeadend import skipped or failed; postprocessing disabled for: %s",
                    recording.title,
                )
                continue

            changed_files = True
            converted_for_delete.append(converted)

            if show_tvh_json:
                print(self.tvheadend.build_json(recording, converted))

            self.mqtt.publish_runtime_status(
                state="finished",
                source=recording.source,
                encoder=converted.encoder_name,
                current_file=converted.output_file.name,
                fullpath=str(converted.output_file),
                current_title=recording.title,
                progress=100,
                eta="00:00",
                queue={"current": index, "total": total},
            )

        if changed_files and not dry_run:
            self.idle.wait_until_idle()
            plex_ok = self.plex.refresh()

            if plex_ok:
                self.idle.wait_until_idle()
                for converted in converted_for_delete:
                    self._delete_source_if_configured(converted)
            else:
                logger.error("Plex refresh failed. Source files will not be deleted.")

    def _delete_source_if_configured(self, converted) -> None:
        src_cfg = source_config(self.config)

        if getattr(converted.source, "deletepending", False):
            logger.info(
                "Refusing to delete deletepending source file: %s",
                converted.source.filename,
            )
            return

        if not bool(src_cfg.get("delete_after_import", False)):
            return

        source = converted.source.filename
        target = converted.output_file

        if source.resolve() == target.resolve():
            logger.error("Refusing to delete source because source and target are identical: %s", source)
            return

        if not source.exists():
            logger.warning("Source file already missing: %s", source)
            return

        source.unlink()
        logger.info("Deleted source file: %s", source)

    def _print_plan(self, recording, plan, index: int, total: int, show_ffmpeg: bool, show_tvh_json: bool) -> None:
        print("-" * 60)
        print(f"[{index}/{total}] [{recording.source}] {recording.starttime} | {recording.title}")
        print(f"Input: {recording.filename}")
        print(f"Output: {plan.output_file}")

        if plan.encoder_name == "none":
            print("Mode: none (copy without transcoding)")
        else:
            print(f"Temp: {plan.temp_file}")
            print(f"Video: {plan.media.video_codec} {plan.media.width}x{plan.media.height} -> {plan.encoder_name}")
            print(f"Audio: stream {plan.media.audio_stream_index} {plan.media.audio_codec}")
            print(f"Profile: {plan.media.profile.name}")

        if show_ffmpeg and plan.command:
            print("FFmpeg:")
            print(" ".join(plan.command))

        if show_tvh_json:
            from models import ConvertedRecording

            dummy = ConvertedRecording(
                source=recording,
                output_file=plan.output_file,
                duration_seconds=plan.media.duration_seconds,
                input_size=recording.filename.stat().st_size,
                output_size=0,
                encoder_name=plan.encoder_name,
                profile_name=plan.media.profile.name,
            )
            print("Tvheadend JSON:")
            print(self.tvheadend.build_json(recording, dummy))

    def _sleep_poll_interval(self) -> None:
        interval = int(self.config.get("service", {}).get("poll_interval", 300))

        for _ in range(interval):
            if self.control.stop_requested or self.control.reload_requested:
                return
            time.sleep(1)


def main():
    configure_logging()

    parser = argparse.ArgumentParser(description="Convert TV recordings and import them into TVHeadend.")
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show-ffmpeg", action="store_true")
    parser.add_argument("--show-tvh-json", action="store_true")
    args = parser.parse_args()

    app = App(args.config)
    app.run(args.dry_run, args.show_ffmpeg, args.show_tvh_json)


if __name__ == "__main__":
    main()
