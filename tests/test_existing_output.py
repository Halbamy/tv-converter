from __future__ import annotations

import unittest

from ffprobe_utils import is_tv_converter_output, normalized_format_tags


class ExistingOutputTest(unittest.TestCase):
    def test_encoded_by_is_case_insensitive(self):
        data = {"format": {"tags": {"ENCODED_BY": "tv-converter 2.3.0"}}}
        self.assertTrue(is_tv_converter_output(data))

    def test_unrelated_encoded_by_is_not_processed(self):
        data = {"format": {"tags": {"encoded_by": "another-tool"}}}
        self.assertFalse(is_tv_converter_output(data))

    def test_tags_are_normalized(self):
        data = {"format": {"tags": {"TITLE": "Example", "encoded_by": "tool"}}}
        self.assertEqual(
            normalized_format_tags(data),
            {"title": "Example", "encoded_by": "tool"},
        )


if __name__ == "__main__":
    unittest.main()
