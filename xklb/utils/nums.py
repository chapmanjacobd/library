import re
from datetime import timezone
from typing import Optional


def percent(value, total):
    if total == 0:
        return 0
    return (value / total) * 100


def to_timestamp(dt_object):
    return int(dt_object.replace(tzinfo=timezone.utc).timestamp())


def safe_int(s) -> Optional[int]:
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def human_to_bytes(input_str) -> int:
    byte_map = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4, "pb": 1024**5}

    input_str = input_str.strip().lower()

    value = re.findall(r"\d+\.?\d*", input_str)[0]
    unit = re.findall(r"[a-z]+", input_str, re.IGNORECASE)

    if unit:
        unit = unit[0]
        unit = "".join(unit.split("i"))

        if not unit.endswith("b"):  # handle cases like 'k'
            unit += "b"
    else:
        unit = "mb"

    unit_multiplier = byte_map.get(unit, 1024**2)  # default to MB
    return int(float(value) * unit_multiplier)


def human_to_seconds(input_str) -> int:
    time_units = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "h": 3600,
        "hr": 3600,
        "hour": 3600,
        "d": 86400,
        "day": 86400,
        "w": 604800,
        "week": 604800,
        "mo": 2592000,
        "mon": 2592000,
        "month": 2592000,
        "y": 31536000,
        "yr": 31536000,
        "year": 31536000,
    }

    input_str = input_str.strip().lower()

    value = re.findall(r"\d+\.?\d*", input_str)[0]
    unit = re.findall(r"[a-z]+", input_str, re.IGNORECASE)

    if unit:
        unit = unit[0]
        if unit != "s":
            unit = unit.rstrip("s")
    else:
        unit = "m"

    return int(float(value) * time_units[unit])
