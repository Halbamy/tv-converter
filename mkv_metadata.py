from __future__ import annotations

def normalized_format_tags(data: dict)->dict[str,str]:
    tags=data.get("format",{}).get("tags",{}) or {}
    return {str(k).lower():str(v) for k,v in tags.items()}

def is_tv_converter_output(data: dict)->bool:
    encoded_by=normalized_format_tags(data).get("encoded_by","")
    return encoded_by.strip().lower().startswith("tv-converter")
