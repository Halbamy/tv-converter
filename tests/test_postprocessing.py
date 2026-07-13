from __future__ import annotations

import unittest
import warnings
from unittest.mock import Mock, patch

from urllib3.exceptions import InsecureRequestWarning

from postprocessing import PlexPostprocessor


class PlexPostprocessorTest(unittest.TestCase):
    def _processor(self, suppress_ssl_warning: bool) -> PlexPostprocessor:
        return PlexPostprocessor(
            {
                "plex": {
                    "enabled": True,
                    "refresh_url": "https://plex/library/sections/all/refresh",
                    "verify_ssl": False,
                    "suppress_ssl_warning": suppress_ssl_warning,
                }
            }
        )

    @patch("postprocessing.requests.get")
    def test_suppresses_insecure_request_warning_when_configured(self, get):
        get.side_effect = self._warn_and_respond

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertTrue(self._processor(True).refresh())

        self.assertEqual(caught, [])
        get.assert_called_once_with(
            "https://plex/library/sections/all/refresh",
            timeout=10,
            verify=False,
        )

    @patch("postprocessing.requests.get")
    def test_keeps_insecure_request_warning_by_default(self, get):
        get.side_effect = self._warn_and_respond

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertTrue(self._processor(False).refresh())

        self.assertEqual(len(caught), 1)
        self.assertIs(caught[0].category, InsecureRequestWarning)

    @patch("postprocessing.requests.get")
    def test_forced_refresh_runs_when_automatic_postprocessing_is_disabled(self, get):
        get.return_value = Mock()
        processor = PlexPostprocessor(
            {
                "plex": {
                    "enabled": False,
                    "refresh_url": "https://plex/library/sections/all/refresh",
                    "verify_ssl": True,
                }
            }
        )

        self.assertTrue(processor.refresh(force=True))

        get.assert_called_once_with(
            "https://plex/library/sections/all/refresh",
            timeout=10,
            verify=True,
        )

    @staticmethod
    def _warn_and_respond(*args, **kwargs):
        warnings.warn("Unverified HTTPS request", InsecureRequestWarning)
        response = Mock()
        response.raise_for_status.return_value = None
        return response


if __name__ == "__main__":
    unittest.main()
