from __future__ import annotations

from pathlib import Path
import os


class PermissionManager:
    def __init__(self, config: dict):
        cfg = config.get("permissions", {})
        self.file_mode = int(str(cfg.get("file_mode", "664")), 8)

    def file(self, path: Path) -> None:
        try:
            os.chmod(path, self.file_mode)
        except PermissionError:
            pass
