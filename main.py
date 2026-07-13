#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

from config import ConfigError, destination_config, load_config, source_config
from converter import Converter
from event_logger import configure_logging, logger
from mqtt_controller import MQTTController, ServiceControl
from postprocessing import PlexPostprocessor
from recording_queue import RecordingQueue
from sources import create_source
from tvheadend import TVHeadendImporter, TVHeadendMovedRecordingRepair, TVHeadendStateMonitor


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
        self.control_event = threading.Event()
        self.queue = RecordingQueue()
        self.source = create_source(self.config)
        self.mqtt = MQTTController(self.config.get("mqtt", {}), lambda: None, self.control)
        self.converter: Converter | None = None
        self._configure_components()

    def _configure_components(self) -> None:
        source_cfg = source_config(self.config)
        destination_cfg = destination_config(self.config)
        source_type = self.config["source"].get("type", "mythtv")
        monitor_cfg = source_cfg if source_type == "tvheadend" else destination_cfg

        self.tvheadend = TVHeadendImporter(
            destination_cfg,
            source_cfg if source_type == "tvheadend" else None,
        )
        self.state_monitor = TVHeadendStateMonitor(monitor_cfg)
        self.plex = PlexPostprocessor(self.config.get("postprocessing", {}))

    def request_reload(self, signum=None, frame=None) -> None:
        logger.info("Reload requested.")
        self.control.reload_requested = True
        self.control_event.set()

    def reload(self) -> None:
        logger.info("Reloading configuration.")
        self.source.stop()
        self.config = load_config(self.config_path)
        self.source = create_source(self.config)
        self._configure_components()
        self.control.reload_requested = False
        self.control_event.clear()
        self.source.start()

    def stop(self, signum=None, frame=None) -> None:
        self.control.stop_requested = True
        self.control_event.set()
        self.source.stop()

        if self.converter is not None:
            self.converter.runner.terminate()

    def run(self, dry_run: bool, show_ffmpeg: bool, show_tvh_json: bool) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGHUP, self.request_reload)

        self.converter = Converter(self.config, self.mqtt)
        self.mqtt.process_getter = lambda: self.converter.runner.process
        self.mqtt.start()
        self.source.start()

        try:
            self._scan_source()

            while not self.control.stop_requested:
                if self.control.reload_requested:
                    self.reload()
                    self._scan_source()

                if len(self.queue) == 0:
                    self.mqtt.publish_runtime_status(
                        state="idle",
                        progress=0,
                        queue={"current": 0, "total": 0},
                    )

                    if not self.source.wait_for_changes(self.control_event):
                        continue

                    self._scan_source()
                    continue

                self._process_next(dry_run, show_ffmpeg, show_tvh_json)

                if self.source.changes_pending():
                    self._scan_source()
        finally:
            self.source.stop()
            self.mqtt.stop()

    def _scan_source(self) -> None:
        # Clear the previous notification before scanning so an event arriving
        # during the REST/database query remains pending for the next scan.
        self.source.mark_scanned()
        recordings = filter_recordings(self.source.get_recordings(), self.config)
        added = self.queue.add_new(recordings)
        logger.info("%s new recording(s) found.", added)

    def _process_next(self, dry_run: bool, show_ffmpeg: bool, show_tvh_json: bool) -> None:
        recording = self.queue.pop()

        if recording is None:
            return

        index = self.queue.current
        total = self.queue.total

        if getattr(recording, "deletepending", False):
            logger.info("Skipping deletepending recording: %s", recording.title)
            return

        assert self.converter is not None
        plan = self.converter.prepare(recording)

        if dry_run:
            self._print_plan(recording, plan, index, total, show_ffmpeg, show_tvh_json)
            return

        if plan.action in {"skip_processed", "manual_review"}:
            self.converter.convert(recording, index, total, plan)
            return

        self._wait_until_tvh_not_busy()

        try:
            converted = self.converter.convert(recording, index, total, plan)
        except RuntimeError as exc:
            logger.error("%s", exc)
            self.control.stop_requested = True
            return

        if converted is None:
            return

        self._wait_until_tvh_not_busy()
        import_ok = self.tvheadend.import_recording(recording, converted)

        if not import_ok:
            logger.info(
                "TVHeadend import skipped or failed; postprocessing disabled for: %s",
                recording.title,
            )
            return

        if show_tvh_json:
            print(self.tvheadend.build_json(recording, converted))

        plex_ok = self.plex.refresh()
        if not plex_ok:
            logger.error("Plex refresh failed. Continuing with source file deletion.")

        self._delete_source_if_configured(converted)
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

    def _wait_until_tvh_not_busy(self) -> None:
        def publish_busy(recordings: int, subscriptions: int) -> None:
            self.mqtt.publish_runtime_status(
                state="paused (tvh busy)",
                tvh={"recordings": recordings, "subscriptions": subscriptions},
                queue={"current": self.queue.current, "total": self.queue.total},
            )

        def publish_ready() -> None:
            self.mqtt.publish_runtime_status(
                state=self.mqtt.state.state.lower(),
                queue={"current": self.queue.current, "total": self.queue.total},
            )

        self.state_monitor.wait_until_not_busy(
            on_busy=publish_busy,
            on_ready=publish_ready,
        )

    def _delete_source_if_configured(self, converted) -> None:
        dst_cfg = destination_config(self.config)

        if getattr(converted.source, "deletepending", False):
            logger.info(
                "Refusing to delete deletepending source file: %s",
                converted.source.filename,
            )
            return

        if not bool(dst_cfg.get("delete_source_after_import", False)):
            return

        if converted.source.source == "mythtv":
            logger.info(
                "Source deletion is disabled for MythTV recordings: %s",
                converted.source.filename,
            )
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

    def _print_plan(
        self,
        recording,
        plan,
        index: int,
        total: int,
        show_ffmpeg: bool,
        show_tvh_json: bool,
    ) -> None:
        print("-" * 60)
        print(f"[{index}/{total}] [{recording.source}] {recording.starttime} | {recording.title}")
        print(f"Input: {recording.filename}")
        print(f"Output: {plan.output_file}")

        if plan.action == "skip_processed":
            print("Mode: already processed by tv-converter (skip)")
        elif plan.action == "manual_review":
            print("Mode: manual review required (skip)")
            print(f"Reason: {plan.message}")
        elif plan.action == "metadata_remux":
            print("Mode: legacy HEVC metadata-only remux")
            print(f"Temp: {plan.temp_file}")
        elif plan.encoder_name == "none":
            print("Mode: none (copy without transcoding)")
        else:
            print(f"Temp: {plan.temp_file}")

        if plan.media is not None and plan.action not in {"skip_processed", "manual_review"}:
            print(
                f"Video: {plan.media.video_codec} "
                f"{plan.media.width}x{plan.media.height} -> {plan.encoder_name}"
            )
            print(f"Audio: stream {plan.media.audio_stream_index} {plan.media.audio_codec}")
            print(f"Profile: {plan.media.profile.name}")

        if show_ffmpeg and plan.command:
            print("FFmpeg:")
            print(" ".join(plan.command))

        if show_tvh_json and plan.media is not None and plan.action not in {"skip_processed", "manual_review"}:
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
            print("TVHeadend JSON:")
            print(self.tvheadend.build_json(recording, dummy))


def main() -> int:
    configure_logging()

    parser = argparse.ArgumentParser(description="Convert TV recordings and import them into TVHeadend.")
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show-ffmpeg", action="store_true")
    parser.add_argument("--show-tvh-json", action="store_true")
    command = parser.add_mutually_exclusive_group()
    command.add_argument(
        "--repair-moved-recordings",
        action="store_true",
        help="repair missing TVHeadend recording paths using dvr/entry/filemoved",
    )
    command.add_argument(
        "--refresh-plex",
        action="store_true",
        help="call the configured Plex refresh URL and exit",
    )
    parser.add_argument(
        "--search-directory",
        action="append",
        default=[],
        metavar="DIRECTORY",
        help="additional directory to search recursively (repeatable)",
    )
    args = parser.parse_args()

    if args.search_directory and not args.repair_moved_recordings:
        parser.error("--search-directory requires --repair-moved-recordings")

    try:
        if args.refresh_plex:
            config = load_config(args.config)
            plex = PlexPostprocessor(config.get("postprocessing", {}))
            return 0 if plex.refresh(force=True) else 1

        if args.repair_moved_recordings:
            config = load_config(args.config)
            destination = destination_config(config)
            directories = [Path(destination["output"]["directory"])]
            directories.extend(Path(value) for value in args.search_directory)
            repair = TVHeadendMovedRecordingRepair(destination)
            result = repair.repair(directories, dry_run=args.dry_run)
            logger.info(
                "Moved recording repair completed "
                "(checked=%s, missing=%s, found=%s, updated=%s, not_found=%s, "
                "without_filename=%s, intentionally_removed=%s, other_removed=%s, errors=%s).",
                result.checked,
                result.missing,
                result.found,
                result.updated,
                result.not_found,
                result.without_filename,
                result.intentionally_removed,
                result.other_removed,
                result.errors,
            )
            return 1 if result.errors else 0

        app = App(args.config)
    except ConfigError as exc:
        print(f"tv-converter: configuration error: {exc}", file=sys.stderr)
        print(file=sys.stderr)
        parser.print_help(sys.stderr)
        return 2

    app.run(args.dry_run, args.show_ffmpeg, args.show_tvh_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
