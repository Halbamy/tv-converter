from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from config import ConfigError, load_config


class ConfigLoadingTest(unittest.TestCase):
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
