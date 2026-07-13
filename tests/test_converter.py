from __future__ import annotations

from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from converter import Converter


class ConverterLoggingTest(unittest.TestCase):
    def test_start_message_includes_encoder_and_profile(self):
        converter = Converter.__new__(Converter)
        converter.encoder = Mock()
        converter.runner = Mock()
        converter.runner.run.return_value = 1
        converter.runner.last_stderr = "conversion failed"
        converter.status = Mock()
        converter.mqtt = Mock()
        converter.mqtt.control.stop_requested = False
        converter._status_stop = threading.Event()
        converter._start_status_thread = Mock()
        converter._stop_status_thread = Mock()

        recording = SimpleNamespace(filename=Path("recording.ts"))
        plan = SimpleNamespace(
            action="transcode",
            output_file=Path("recording.mkv"),
            temp_file=Path("recording.mkv.part"),
            media=SimpleNamespace(profile=SimpleNamespace(name="hd")),
            encoder_name="hevc_qsv",
            command=["ffmpeg"],
        )

        with self.assertLogs("tv-converter", level="INFO") as logs:
            with self.assertRaises(RuntimeError):
                converter.convert(recording, 1, 1, plan)

        self.assertIn(
            "Starting conversion: recording.mkv (encoder=hevc_qsv, profile=hd)",
            logs.output[0],
        )


if __name__ == "__main__":
    unittest.main()
