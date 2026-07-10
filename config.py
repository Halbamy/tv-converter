from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    pass


def load_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)

    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not isinstance(cfg, dict):
        raise ConfigError("Config file is empty or invalid.")

    validate_config(cfg)
    return cfg


def section(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    value = cfg.get(name)

    if not isinstance(value, dict):
        raise ConfigError(f"Missing config section: {name}")

    return value


def source_config(cfg: dict[str, Any]) -> dict[str, Any]:
    source = section(cfg, "source")
    source_type = source.get("type", "mythtv")
    return section(source, source_type)


def validate_config(cfg: dict[str, Any]) -> None:
    source = section(cfg, "source")
    encoder = section(cfg, "encoder")
    profiles = section(cfg, "profiles")

    source_type = source.get("type", "mythtv")
    if source_type not in {"mythtv", "tvheadend"}:
        raise ConfigError("source.type must be mythtv or tvheadend")

    src = section(source, source_type)
    out = section(src, "output")
    if not out.get("directory"):
        raise ConfigError(f"source.{source_type}.output.directory is required")

    if source_type == "mythtv":
        for key in ("host", "user", "password", "database"):
            if not src.get(key):
                raise ConfigError(f"source.mythtv.{key} is required")

    if source_type == "tvheadend" and not src.get("url"):
        raise ConfigError("source.tvheadend.url is required")

    if encoder.get("type", "auto") not in {"auto", "sw", "qsv", "vaapi", "none", "software", "libx265"}:
        raise ConfigError("encoder.type must be auto, sw, qsv, vaapi or none")

    for name, profile in profiles.items():
        for key in ("min_height", "preset", "crf", "qsv_global_quality", "vaapi_qp"):
            if key not in profile:
                raise ConfigError(f"profiles.{name}.{key} is required")


def is_verbose(cfg: dict[str, Any]) -> bool:
    return cfg.get("logging", {}).get("level", "normal") in {"verbose", "debug"}
