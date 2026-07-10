from __future__ import annotations

import sys


class StatusDisplay:
    def __init__(self):
        self.enabled = sys.stdout.isatty()
        self.last_line = ""

    def update(
        self,
        *,
        file_index: int,
        file_count: int,
        power: str,
        state: str,
        filename: str,
        percent: str,
        speed: str,
        eta: str,
    ) -> None:
        if not self.enabled:
            return

        line = (
            f"[{file_index}/{file_count}] "
            f"Power: {power}W | "
            f"{state:<12} | "
            f"{filename} | "
            f"{percent} | "
            f"speed={speed} | "
            f"ETA={eta}"
        )

        if line == self.last_line:
            return

        sys.stdout.write("\r\033[K" + line)
        sys.stdout.flush()
        self.last_line = line

    def finish(self) -> None:
        if self.enabled and self.last_line:
            sys.stdout.write("\n")
            sys.stdout.flush()
        self.last_line = ""
