from __future__ import annotations

import ipaddress
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

    service = cfg.get("service", {})

    try:
        poll_interval = int(service.get("poll_interval", 300))
    except (TypeError, ValueError) as exc:
        raise ConfigError("service.poll_interval must be an integer") from exc

    if poll_interval < 0:
        raise ConfigError("service.poll_interval must be greater than or equal to zero")

    http = cfg.get("http", {})
    http_enabled = bool(http.get("enabled", False))

    if poll_interval == 0 and not http_enabled:
        raise ConfigError(
            "service.poll_interval is zero, but the HTTP wakeup service is disabled"
        )

    if http_enabled:
        bind = str(http.get("bind", "")).strip()
        allowed = str(http.get("allow", "")).strip()
        token = str(http.get("token", ""))

        if not bind:
            raise ConfigError("http.bind is required when HTTP wakeup is enabled")

        try:
            bind_address = ipaddress.ip_address(bind)
        except ValueError as exc:
            raise ConfigError("http.bind must be an IPv4 or IPv6 address") from exc

        try:
            port = int(http.get("port", 8080))
        except (TypeError, ValueError) as exc:
            raise ConfigError("http.port must be an integer") from exc

        if not 1 <= port <= 65535:
            raise ConfigError("http.port must be between 1 and 65535")

        if not allowed:
            raise ConfigError("http.allow is required when HTTP wakeup is enabled")

        if allowed == "0.0.0.0":
            allowed = "0.0.0.0/0"
        elif allowed == "::":
            allowed = "::/0"

        try:
            allowed_network = ipaddress.ip_network(allowed, strict=False)
        except ValueError as exc:
            raise ConfigError("http.allow must be an IP address or CIDR network") from exc

        if bind_address.version != allowed_network.version:
            raise ConfigError("http.bind and http.allow must use the same IP version")

        if not token:
            raise ConfigError("http.token must not be empty when HTTP wakeup is enabled")


def is_verbose(cfg: dict[str, Any]) -> bool:
    return cfg.get("logging", {}).get("level", "normal") in {"verbose", "debug"}
