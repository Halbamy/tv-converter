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


def destination_config(cfg: dict[str, Any]) -> dict[str, Any]:
    destination = section(cfg, "destination")
    destination_type = destination.get("type", "tvheadend")
    return section(destination, destination_type)


def validate_authentication(config: dict[str, Any], path: str) -> None:
    authentication = config.get("authentication") or {}
    auth_type = authentication.get("type", "basic")

    if auth_type not in {"basic", "persistent_auth"}:
        raise ConfigError(f"{path}.authentication.type must be basic or persistent_auth")

    if auth_type == "basic":
        if not authentication.get("username") or not authentication.get("password"):
            raise ConfigError(
                f"{path}.authentication.username and password are required for basic auth"
            )
    elif not authentication.get("auth_code"):
        raise ConfigError(f"{path}.authentication.auth_code is required")


def validate_config(cfg: dict[str, Any]) -> None:
    source = section(cfg, "source")
    destination = section(cfg, "destination")
    encoder = section(cfg, "encoder")
    profiles = section(cfg, "profiles")

    source_type = source.get("type", "mythtv")
    if source_type not in {"mythtv", "tvheadend"}:
        raise ConfigError("source.type must be mythtv or tvheadend")

    src = section(source, source_type)

    if source_type == "mythtv":
        for key in ("host", "user", "password", "database"):
            if not src.get(key):
                raise ConfigError(f"source.mythtv.{key} is required")

        try:
            poll_interval = int(src.get("poll_interval", 300))
        except (TypeError, ValueError) as exc:
            raise ConfigError("source.mythtv.poll_interval must be an integer") from exc

        if poll_interval <= 0:
            raise ConfigError("source.mythtv.poll_interval must be greater than zero")
    else:
        if not src.get("url"):
            raise ConfigError("source.tvheadend.url is required")
        validate_authentication(src, "source.tvheadend")

    destination_type = destination.get("type", "tvheadend")
    if destination_type != "tvheadend":
        raise ConfigError("destination.type must currently be tvheadend")

    dst = section(destination, "tvheadend")
    if not dst.get("url"):
        raise ConfigError("destination.tvheadend.url is required")
    validate_authentication(dst, "destination.tvheadend")

    output = section(dst, "output")
    if not output.get("directory"):
        raise ConfigError("destination.tvheadend.output.directory is required")

    if encoder.get("type", "auto") not in {
        "auto",
        "sw",
        "qsv",
        "vaapi",
        "none",
        "software",
        "libx265",
    }:
        raise ConfigError("encoder.type must be auto, sw, qsv, vaapi or none")

    for name, profile in profiles.items():
        for key in ("min_height", "preset", "crf", "qsv_global_quality", "vaapi_qp"):
            if key not in profile:
                raise ConfigError(f"profiles.{name}.{key} is required")


def is_verbose(cfg: dict[str, Any]) -> bool:
    return cfg.get("logging", {}).get("level", "normal") in {"verbose", "debug"}
