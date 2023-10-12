import re

from xklb.utils.log_utils import log


def compare_block_strings(value, media_value):
    if value is None and media_value is None:
        return True
    elif value is None or media_value is None:
        return False

    value = value.lower()
    media_value = media_value.lower()

    starts_with_wild = value.startswith("%")
    ends_with_wild = value.endswith("%")
    inner_value = value.lstrip("%").rstrip("%")
    inner_wild = "%" in inner_value

    if inner_wild:
        regex_pattern = ".*".join(re.escape(s) for s in value.split("%"))
        return bool(re.match(regex_pattern, media_value))
    elif not ends_with_wild and not starts_with_wild:
        return media_value.startswith(value)
    elif ends_with_wild and not starts_with_wild:
        return media_value.startswith(value.rstrip("%"))
    elif starts_with_wild and not ends_with_wild:
        return media_value.endswith(value.lstrip("%"))
    elif starts_with_wild and ends_with_wild:
        return inner_value in media_value
    raise ValueError("Unreachable?")


def is_blocked_dict_like_sql(m, blocklist):
    for block_dict in blocklist:
        for key, value in block_dict.items():
            if key in m and compare_block_strings(value, m[key]):
                log.info("%s matched %s block rule 「%s」 %s", key, value, m[key], m.get("path"))
                return True
    return False


def block_dicts_like_sql(media, blocklist):
    return [m for m in media if not is_blocked_dict_like_sql(m, blocklist)]


def allow_dicts_like_sql(media, allowlist):
    allowed_media = []
    for m in media:
        is_blocked = False
        for block_dict in allowlist:
            for key, value in block_dict.items():
                if key in m and compare_block_strings(value, m[key]):
                    is_blocked = True
                    break
            if is_blocked:
                break
        if is_blocked:
            allowed_media.append(m)

    return allowed_media


def parse_human_to_sql(human_to_x, var, sizes) -> str:
    size_rules = ""

    for size in sizes:
        if ">" in size:
            size_rules += f"and {var} > {human_to_x(size.lstrip('>'))} "
        elif "<" in size:
            size_rules += f"and {var} < {human_to_x(size.lstrip('<'))} "
        elif "+" in size:
            size_rules += f"and {var} >= {human_to_x(size.lstrip('+'))} "
        elif "-" in size:
            size_rules += f"and {human_to_x(size.lstrip('-'))} >= {var} "
        else:
            # approximate size rule +-10%
            size_bytes = human_to_x(size)
            size_rules += (
                f"and {int(size_bytes + (size_bytes /10))} >= {var} and {var} >= {int(size_bytes - (size_bytes /10))} "
            )
    return size_rules


def parse_human_to_lambda(human_to_x, sizes):
    return lambda var: all(
        (
            (var > human_to_x(size.lstrip(">")))
            if ">" in size
            else (var < human_to_x(size.lstrip("<")))
            if "<" in size
            else (var >= human_to_x(size.lstrip("+")))
            if "+" in size
            else (human_to_x(size.lstrip("-")) >= var)
            if "-" in size
            else (
                int(human_to_x(size) + (human_to_x(size) / 10))
                >= var
                >= int(human_to_x(size) - (human_to_x(size) / 10))
            )
        )
        for size in sizes
    )
