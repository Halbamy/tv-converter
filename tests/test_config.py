from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from config import ConfigError, destination_config, load_config, validate_config
from encoder import Encoder


class ConfigLoadingTest(unittest.TestCase):
    def test_output_original_shorthand_is_normalized(self):
        config = self._valid_config("original")

        validate_config(config)

        self.assertEqual(
            destination_config(config)["output"],
            {"mode": "original"},
        )

    def test_expanded_original_is_normalized(self):
        output = {"directory": "original"}
        config = self._valid_config(output)

        validate_config(config)

        self.assertEqual(
            destination_config(config)["output"],
            {"mode": "original"},
        )

        recording = unittest.mock.Mock(filename=Path("/media/source/recording.ts"))
        self.assertEqual(
            Encoder(config).output_directory(recording),
            Path("/media/source"),
        )

    def test_shorthand_original_uses_source_directory(self):
        config = self._valid_config("original")
        recording = unittest.mock.Mock(filename=Path("/media/source/recording.ts"))

        self.assertEqual(
            Encoder(config).output_directory(recording),
            Path("/media/source"),
        )

    def test_expanded_output_directory_remains_supported(self):
        output = {"directory": "/media/recordings"}
        config = self._valid_config(output)

        validate_config(config)

        self.assertEqual(destination_config(config)["output"], output)

    @staticmethod
    def _valid_config(output):
        authentication = {
            "type": "basic",
            "username": "user",
            "password": "password",
        }
        profile = {
            "min_height": 0,
            "preset": "fast",
            "crf": 24,
            "qsv_global_quality": 24,
            "vaapi_qp": 25,
        }
        return {
            "source": {
                "type": "tvheadend",
                "tvheadend": {
                    "url": "http://source",
                    "authentication": authentication,
                },
            },
            "destination": {
                "type": "tvheadend",
                "tvheadend": {
                    "url": "http://destination",
                    "authentication": authentication,
                    "output": output,
                },
            },
            "encoder": {"type": "auto"},
            "profiles": {"sd": profile},
        }

    def test_permission_error_is_reported_as_config_error(self):
        error = PermissionError(13, "Permission denied")

        with (
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "open", side_effect=error),
            self.assertRaisesRegex(ConfigError, "Permission denied"),
        ):
            load_config("/etc/tv-converter/config.yaml")


if __name__ == "__main__":
    unittest.main()
