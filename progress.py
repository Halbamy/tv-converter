from __future__ import annotations

from models import Progress


class ProgressParser:
    def __init__(self):
        self.progress = Progress()

    def reset(self) -> None:
        self.progress = Progress()

    def feed(self, line: str) -> bool:
        line = line.strip()

        if "=" not in line:
            return False

        key, value = line.split("=", 1)

        try:
            if key == "speed":
                self.progress.speed = float(value.replace("x", ""))
            elif key in {"out_time_ms", "out_time_us"}:
                self.progress.out_time_us = int(value)
            elif key == "progress":
                return True
        except ValueError:
            return False

        return False
