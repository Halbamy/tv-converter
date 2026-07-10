from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable

from config import is_verbose
from models import Progress
from progress import ProgressParser


class FFmpegRunner:
    def __init__(self, config: dict):
        self.config = config
        self.process: subprocess.Popen | None = None
        self.parser = ProgressParser()
        self.last_stderr = ""

    @property
    def progress(self) -> Progress:
        return self.parser.progress

    def run(
        self,
        command: list[str],
        callback: Callable[[Progress, bool], None] | None = None,
    ) -> int:
        self.parser.reset()
        self.last_stderr = ""

        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        assert self.process.stdout is not None
        assert self.process.stderr is not None
        stderr_lines: list[str] = []

        def read_stderr() -> None:
            assert self.process is not None
            assert self.process.stderr is not None

            for line in self.process.stderr:
                stderr_lines.append(line)

                if is_verbose(self.config):
                    print(line, end="")

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        for line in self.process.stdout:
            if self.parser.feed(line) and callback is not None:
                callback(self.progress, False)

        rc = self.process.wait()
        stderr_thread.join(timeout=2)
        self.last_stderr = "".join(stderr_lines)

        if callback is not None:
            callback(self.progress, True)

        return rc

    def terminate(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
