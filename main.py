#!/usr/bin/env python3
from __future__ import annotations

import argcomplete
import argparse
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from config import ConfigError, destination_config, load_config, source_config
from converter import Converter
from event_logger import configure_logging, logger
from mqtt_controller import MQTTController, ServiceControl
from postprocessing import PlexPostprocessor
from recording_queue import RecordingQueue
from sources import create_source
from tvheadend import TVHeadendImporter, TVHeadendMovedRecordingRepair, TVHeadendStateMonitor, TVHeadendRecordingRenamer, TVHeadendRecordingSearcher, TVHeadendRecordingTranscoder


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


def delete_source_if_configured(
    config: dict,
    recording,
    target: Path,
    dry_run: bool = False,
) -> None:
    dst_cfg = destination_config(config)

    if getattr(recording, "deletepending", False):
        logger.info(
            "Refusing to delete deletepending source file: %s",
            recording.filename,
        )
        return

    if not bool(dst_cfg.get("delete_source_after_import", False)):
        return

    if recording.source == "mythtv":
        logger.info(
            "Source deletion is disabled for MythTV recordings: %s",
            recording.filename,
        )
        return

    source = recording.filename

    if source.resolve() == target.resolve():
        logger.error("Refusing to delete source because source and target are identical: %s", source)
        return

    if not source.exists():
        logger.warning("Source file already missing: %s", source)
        return

    if dry_run:
        logger.info("Would delete source file after successful TVHeadend update: %s", source)
        return

    source.unlink()
    logger.info("Deleted source file: %s", source)


class App:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.control = ServiceControl()
        self.control_event = threading.Event()
        self.stop_event = threading.Event()
        self.queue = RecordingQueue()
        self.source = create_source(self.config)
        self.mqtt = MQTTController(self.config.get("mqtt", {}), lambda: None, self.control)
        self.converter: Converter | None = None
        self._tvh_monitor_thread: threading.Thread | None = None
        self._tvh_monitor_stop = threading.Event()
        self._recording_removed = threading.Event()
        self._configure_components()

    def _configure_components(self) -> None:
        source_cfg = source_config(self.config)
        destination_cfg = destination_config(self.config)
        source_type = self.config["source"].get("type", "mythtv")
        monitor_cfg = source_cfg if source_type == "tvheadend" else destination_cfg
        change_event = (
            getattr(self.source, "state_change_event", None)
            if source_type == "tvheadend"
            else None
        )

        self.tvheadend = TVHeadendImporter(
            destination_cfg,
            source_cfg if source_type == "tvheadend" else None,
        )
        self.state_monitor = TVHeadendStateMonitor(
            monitor_cfg,
            change_event=change_event,
        )
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
        if not self.control.stop_requested:
            logger.info("Stop requested.")

        self.control.stop_requested = True
        self.control_event.set()
        self.stop_event.set()

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
            if plan.action not in {"skip_processed", "manual_review"}:
                delete_source_if_configured(
                    self.config,
                    recording,
                    plan.output_file,
                    dry_run=True,
                )
            return

        if plan.action in {"skip_processed", "manual_review"}:
            self.converter.convert(recording, index, total, plan)
            return

        if not self._wait_until_tvh_not_busy():
            return

        self._start_tvh_runtime_monitor(recording)

        try:
            converted = self.converter.convert(recording, index, total, plan)
        except RuntimeError as exc:
            if self._recording_removed.is_set():
                self._remove_partial_file(plan)
                logger.warning(
                    "Recording was removed while paused; skipping: %s",
                    recording.title,
                )
                return

            logger.error("%s", exc)
            self.control.stop_requested = True
            return
        finally:
            self._stop_tvh_runtime_monitor()

        if converted is None:
            return

        if self._recording_removed.is_set():
            self._remove_partial_file(plan)
            logger.warning(
                "Recording was removed while paused; skipping: %s",
                recording.title,
            )
            return

        if not self._wait_until_tvh_not_busy():
            return
        import_ok = self.tvheadend.import_recording(recording, converted)

        if not import_ok:
            logger.info(
                "TVHeadend import skipped or failed; postprocessing disabled for: %s",
                recording.title,
            )
            return

        if show_tvh_json:
            print(self.tvheadend.build_json(recording, converted))

        self._delete_source_if_configured(converted)

        if not self.plex.refresh():
            logger.error("Final Plex refresh failed.")

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

    def _wait_until_tvh_not_busy(self) -> bool:
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

        return self.state_monitor.wait_until_not_busy(
            on_busy=publish_busy,
            on_ready=publish_ready,
            stop_event=self.stop_event,
        )

    def _start_tvh_runtime_monitor(self, recording) -> None:
        self._recording_removed = threading.Event()
        self._tvh_monitor_stop = threading.Event()
        self._tvh_monitor_thread = None

        if recording.source != "tvheadend" or self.state_monitor.change_event is None:
            return

        self._tvh_monitor_thread = threading.Thread(
            target=self._monitor_tvh_during_conversion,
            args=(recording,),
            name="tvheadend-busy-monitor",
            daemon=True,
        )
        self._tvh_monitor_thread.start()

    def _stop_tvh_runtime_monitor(self) -> None:
        self._tvh_monitor_stop.set()

        if self._tvh_monitor_thread is not None:
            self._tvh_monitor_thread.join(timeout=2)
            self._tvh_monitor_thread = None

        self.mqtt.resume("TVH")

    def _monitor_tvh_during_conversion(self, recording) -> None:
        change_event = self.state_monitor.change_event
        next_fallback_check = time.monotonic() + self.state_monitor.poll_interval
        tvh_busy = False

        while not self._tvh_monitor_stop.is_set() and not self.stop_event.is_set():
            changed = change_event.wait(timeout=0.5)
            now = time.monotonic()
            fallback_due = now >= next_fallback_check

            if not changed and not fallback_due:
                continue

            if changed:
                change_event.clear()

            if tvh_busy and not fallback_due:
                continue

            recordings, subscriptions = self.state_monitor.busy_counts()

            if recordings or subscriptions:
                tvh_busy = True
                next_fallback_check = now + self.state_monitor.busy_recheck_interval
                self.mqtt.pause("TVH")
                continue

            tvh_busy = False
            next_fallback_check = now + self.state_monitor.poll_interval

            if not self.mqtt.is_paused_for("TVH"):
                continue

            entry_exists = self.state_monitor.recording_exists(recording.recording_id)
            file_exists = recording.filename.is_file()

            if not file_exists or entry_exists is False:
                self._recording_removed.set()
                logger.warning(
                    "Recording disappeared while TVHeadend was busy: %s",
                    recording.filename,
                )
                assert self.converter is not None
                self.converter.runner.terminate()
                return

            self.mqtt.resume("TVH")

    @staticmethod
    def _remove_partial_file(plan) -> None:
        if plan.temp_file is not None and plan.temp_file.exists():
            plan.temp_file.unlink()
            logger.info("Removed unfinished conversion: %s", plan.temp_file)

    def _delete_source_if_configured(self, converted) -> None:
        delete_source_if_configured(
            self.config,
            converted.source,
            converted.output_file,
        )

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
            audio_target = "copy" if plan.media.audio_copy else "aac"
            print(
                f"Audio: stream {plan.media.audio_stream_index} "
                f"{plan.media.audio_codec} -> {audio_target}"
            )
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
        "--rename-recordings",
        action="store_true",
        help="rename all completed TVHeadend recordings to the current naming schema",
    )
    command.add_argument(
        "--search",
        metavar="STRING",
        help="search all TVHeadend DVR entries by substring",
    )
    command.add_argument(
        "--transcode",
        action="store_true",
        help="transcode a specific TVHeadend recording (requires --uuid)",
    )
    command.add_argument(
        "--refresh-plex",
        action="store_true",
        help="call the configured Plex refresh URL and exit",
    )
    parser.add_argument(
        "--uuid",
        default=None,
        metavar="UUID",
        help="when used with --rename-recordings, rename only the recording with this UUID",
    )
    parser.add_argument(
        "--search-directory",
        action="append",
        default=[],
        metavar="DIRECTORY",
        help="additional directory to search recursively (repeatable)",
    )
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if args.search_directory and not args.repair_moved_recordings:
        parser.error("--search-directory requires --repair-moved-recordings")

    try:
        if args.refresh_plex:
            config = load_config(args.config)
            plex = PlexPostprocessor(config.get("postprocessing", {}))
            return 0 if plex.refresh(force=True) else 1

        if args.search is not None:
            config = load_config(args.config)
            tvheadend_config = destination_config(config)
            
            if not tvheadend_config.get("enabled", False):
                logger.error("TVHeadend is not enabled in configuration")
                return 1
            
            searcher = TVHeadendRecordingSearcher(tvheadend_config)
            results = searcher.search(args.search)
            
            if not results:
                print("No recordings found matching search criteria.")
                return 0
            
            print(f"\nFound {len(results)} recording(s) matching '{args.search}':\n")
            for result in results:
                start_time = datetime.fromtimestamp(result["start"]).strftime("%Y-%m-%d %H:%M:%S")
                stop_time = datetime.fromtimestamp(result["stop"]).strftime("%Y-%m-%d %H:%M:%S")
                print(f"UUID: {result['uuid']}")
                print(f"  Title: {result['title']}")
                print(f"  Channel: {result['channelname']}")
                print(f"  Start: {start_time}")
                print(f"  Stop: {stop_time}")
                if result['filename']:
                    print(f"  File: {result['filename']}")
                for label, field in (
                    ("Status", "status"),
                    ("Filesize", "filesize"),
                    ("File removed", "fileremoved"),
                    ("Removal", "removal"),
                    ("Duplicate", "duplicate"),
                    ("Comment", "comment"),
                    ("Data errors", "data_errors"),
                    ("Errors", "errors"),
                    ("Error code", "errorcode"),
                ):
                    value = result[field]
                    print(f"  {label}: {'-' if value is None or value == '' else value}")
                print()
            
            return 0

        if args.rename_recordings:
            config = load_config(args.config)
            tvheadend_config = destination_config(config)
            
            if not tvheadend_config.get("enabled", False):
                logger.error("TVHeadend is not enabled in configuration")
                return 1
            
            renamer = TVHeadendRecordingRenamer(tvheadend_config)
            result = renamer.rename_recordings(
                config,
                uuid=args.uuid,
                dry_run=args.dry_run,
            )
            logger.info(
                "Recording rename completed "
                "(checked=%s, renamed=%s, skipped=%s, errors=%s).",
                result.checked,
                result.renamed,
                result.skipped,
                result.errors,
            )
            return 1 if result.errors else 0

        if args.transcode:
            if not args.uuid:
                parser.error("--transcode requires --uuid")

            config = load_config(args.config)
            tvheadend_config = destination_config(config)
            
            if not tvheadend_config.get("enabled", False):
                logger.error("TVHeadend is not enabled in configuration")
                return 1
            
            transcoder = TVHeadendRecordingTranscoder(tvheadend_config)
            recording = transcoder.get_recording_by_uuid(args.uuid)
            
            if not recording:
                logger.error("Could not fetch recording with UUID: %s", args.uuid)
                return 1
            
            if not recording.filename.exists():
                logger.error("Recording file does not exist: %s", recording.filename)
                return 1
            
            logger.info("Starting single recording transcode: %s", recording.title)
            
            # Create a minimal MQTT controller and converter instance
            mqtt = MQTTController(config.get("mqtt", {}), lambda: None, ServiceControl())
            converter = Converter(config, mqtt)
            
            plan = converter.prepare(recording)
            
            if args.dry_run:
                print("-" * 60)
                print(f"[UUID: {recording.recording_id}] {recording.starttime} | {recording.title}")
                print(f"Input: {recording.filename}")
                print(f"Output: {plan.output_file}")
                
                if plan.media is not None and plan.action not in {"skip_processed", "manual_review"}:
                    print(
                        f"Video: {plan.media.video_codec} "
                        f"{plan.media.width}x{plan.media.height} -> {plan.encoder_name}"
                    )
                    audio_target = "copy" if plan.media.audio_copy else "aac"
                    print(
                        f"Audio: stream {plan.media.audio_stream_index} "
                        f"{plan.media.audio_codec} -> {audio_target}"
                    )
                    print(f"Profile: {plan.media.profile.name}")
                elif plan.action == "skip_processed":
                    print("Mode: already processed by tv-converter (skip)")
                elif plan.action == "manual_review":
                    print("Mode: manual review required (skip)")
                    print(f"Reason: {plan.message}")

                if plan.action not in {"skip_processed", "manual_review"}:
                    delete_source_if_configured(
                        config,
                        recording,
                        plan.output_file,
                        dry_run=True,
                    )
                
                return 0
            
            try:
                mqtt.start()
                converted = converter.convert(recording, 1, 1, plan)
                mqtt.stop()
                
                if converted is None:
                    logger.warning("Transcoding did not produce output")
                    return 1
                
                # Update the existing DVR entry so its UUID is preserved.
                try:
                    tvheadend = TVHeadendImporter(tvheadend_config, tvheadend_config)
                    if tvheadend.import_recording(recording, converted):
                        logger.info(
                            "Updated TVHeadend recording after transcode: %s",
                            recording.recording_id,
                        )
                    else:
                        logger.error("TVHeadend recording update was skipped")
                        return 1
                except Exception as exc:
                    logger.error("Could not update TVHeadend recording: %s", exc)
                    return 1

                delete_source_if_configured(
                    config,
                    converted.source,
                    converted.output_file,
                )

                plex = PlexPostprocessor(config.get("postprocessing", {}))
                if not plex.refresh():
                    logger.error("Final Plex refresh failed.")
                
                logger.info("Recording transcode completed successfully: %s", recording.title)
                return 0
            except Exception as exc:
                logger.error("Transcoding failed: %s", exc)
                return 1

        if args.repair_moved_recordings:
            config = load_config(args.config)
            destination = destination_config(config)
            output = destination["output"]
            original_mode = output.get("mode") == "original"
            directories = []

            if not original_mode:
                directories.append(Path(output["directory"]))

            directories.extend(Path(value) for value in args.search_directory)
            repair = TVHeadendMovedRecordingRepair(destination)
            result = repair.repair(
                directories,
                dry_run=args.dry_run,
                search_registered_parent=original_mode,
            )
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
