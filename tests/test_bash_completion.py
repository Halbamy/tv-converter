from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPLETION_SCRIPT = ROOT / "tv-converter-completion.bash"


class BashCompletionTest(unittest.TestCase):
    def test_completion_populates_compreply_from_argcomplete_protocol(self):
        bash_script = f"""
            tv-converter() {{
                [ "${{_ARGCOMPLETE-}}" = 1 ] || return 1
                printf '%s\v%s' '--refresh-plex' '--rename-recordings' >&8
            }}

            source {str(COMPLETION_SCRIPT)!r}
            COMP_LINE='tv-converter --re'
            COMP_POINT=${{#COMP_LINE}}
            COMP_TYPE=9
            COMP_WORDBREAKS=' :='
            _tv_converter_completion tv-converter --re tv-converter
            printf '%s\n' "${{COMPREPLY[@]}}"
        """

        result = subprocess.run(
            ["bash", "-c", bash_script],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            result.stdout.splitlines(),
            ["--refresh-plex", "--rename-recordings"],
        )


if __name__ == "__main__":
    unittest.main()
