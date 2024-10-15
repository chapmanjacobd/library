import math, re, statistics


def percent(value, total):
    if total == 0:
        return 0
    return (value / total) * 100


def float_from_percent(s: str) -> float:
    if s.endswith("%"):
        v = float(s.rstrip("%")) / 100
    else:
        v = float(s)
    return v


def percentage_difference(value1, value2):
    value1 = value1 or 0
    value2 = value2 or 0

    try:
        return abs((value1 - value2) / ((value1 + value2) / 2)) * 100
    except ZeroDivisionError:
        return 100.0


def to_timestamp(dt_object):
    return int(dt_object.timestamp())


def safe_int(s) -> int | None:
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def safe_float(s) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def safe_int_float_str(s):
    try:
        return int(s)
    except ValueError:
        pass

    try:
        return float(s)
    except ValueError:
        return s


def safe_median(l) -> float | None:
    if not l:
        return None
    try:
        return statistics.median(v for v in l if v is not None and v > 0)
    except statistics.StatisticsError:
        return None


def safe_mean(l) -> float | None:
    if not l:
        return None
    try:
        return statistics.mean(v for v in l if v is not None and v > 0)
    except statistics.StatisticsError:
        return None


def human_to_bytes(input_str, binary=True) -> int:
    k = 1024 if binary else 1000
    byte_map = {"b": 1, "k": k, "m": k**2, "g": k**3, "t": k**4, "p": k**5}

    input_str = input_str.strip().lower()

    value = re.findall(r"\d+\.?\d*", input_str)[0]
    unit = re.findall(r"[a-z]+", input_str, re.IGNORECASE)

    unit = unit[0][0] if unit else "m"

    unit_multiplier = byte_map.get(unit, k**2)  # default to MB / MBit
    return int(float(value) * unit_multiplier)


def human_to_bits(input_str) -> int:
    return human_to_bytes(input_str, binary=False)


def sql_human_time(s):
    if s.isdigit():
        return s + " minutes"
    return s.replace("mins", "minutes").replace("secs", "seconds")


def human_to_seconds(input_str):
    if input_str is None:
        return None

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


def linear_interpolation(x, data_points, clip=True) -> float:
    data_points.sort(key=lambda point: point[0])  # Sort the data points based on x values
    n = len(data_points)

    if clip:
        if x < data_points[0][0]:
            return data_points[0][1]
        elif x > data_points[n - 1][0]:
            return data_points[n - 1][1]
    elif x < data_points[0][0]:
        x1, y1 = data_points[0]
        x2, y2 = data_points[1]
        return y1 + ((x - x1) / (x2 - x1)) * (y2 - y1)
    elif x > data_points[n - 1][0]:
        x1, y1 = data_points[n - 2]
        x2, y2 = data_points[n - 1]
        return y1 + ((x - x1) / (x2 - x1)) * (y2 - y1)

    # perform linear interpolation
    for i in range(n - 1):
        if data_points[i][0] <= x <= data_points[i + 1][0]:
            x1, y1 = data_points[i]
            x2, y2 = data_points[i + 1]
            interpolated_y = y1 + ((x - x1) / (x2 - x1)) * (y2 - y1)
            return interpolated_y

    msg = f"Could not determine value y for value x {x}"
    raise ValueError(msg)


def calculate_segments(file_size, chunk_size, gap=0.1):
    segments = []
    start = 0

    if file_size in [None, 0]:
        return []
    elif file_size <= chunk_size * 3:
        return [0]

    end_segment_start = file_size - chunk_size

    while start + chunk_size < end_segment_start:
        end = min(start + chunk_size, file_size)
        segments.append(start)

        if gap < 1:
            gap = math.ceil(file_size * gap)
        start = end + gap

    return segments + [end_segment_start]  # always scan the end
