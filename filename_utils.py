from __future__ import annotations

import re
from pathlib import Path

from models import Recording


def sanitize_filename_part(text: str) -> str:
    text = text.strip()
    replacements = {
        "/": "-",
        "\\": "-",
        ":": "-",
        "*": "_",
        "?": "_",
        '"': "'",
        "<": "_",
        ">": "_",
        "|": "_",
    }

    for source, target in replacements.items():
        text = text.replace(source, target)

    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("._- ")

    return text or "unbekannt"


def build_output_filename(
    recording: Recording,
    output_dir: Path,
    description_fallback_chars: int = 25,
    suffix: str = ".mkv",
) -> Path:
    start = recording.starttime.strftime("%Y%m%d_%H%M")
    title = sanitize_filename_part(recording.title)
    subtitle_source = recording.subtitle.strip()

    if not subtitle_source:
        subtitle_source = recording.description.strip()[:description_fallback_chars]

    if not subtitle_source:
        subtitle_source = "ohne_Untertitel"

    subtitle = sanitize_filename_part(subtitle_source)
    suffix = suffix if suffix.startswith(".") else "." + suffix

    return output_dir / f"{title}_{subtitle}_{start}{suffix}"
