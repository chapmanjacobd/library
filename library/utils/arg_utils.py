import argparse, operator
from collections import defaultdict
from copy import copy
from pathlib import Path

from library.utils import iterables, nums


def override_sort(sort_expression: str) -> str:
    def year_month_sql(var):
        return f"cast(strftime('%Y%m', datetime({var}, 'unixepoch')) as int)"

    def year_month_day_sql(var):
        return f"cast(strftime('%Y%m%d', datetime({var}, 'unixepoch')) as int)"

    return (
        sort_expression.replace("month_created", year_month_sql("time_created"))
        .replace("month_modified", year_month_sql("time_modified"))
        .replace("date_created", year_month_day_sql("time_created"))
        .replace("date_modified", year_month_day_sql("time_modified"))
        .replace("random()", "random")
        .replace("random", "random()")
        .replace("priorityfast", "ntile(1000) over (order by size) desc, duration")
        .replace("priority", "ntile(1000) over (order by size/duration) desc")
        .replace("bitrate", "size/duration desc")
    )


def parse_ambiguous_sort(sort):
    combined_sort = []
    for s in iterables.flatten([s.split(",") for s in sort]):
        if s.strip() in ["asc", "desc"] and combined_sort:
            combined_sort[-1] += " " + s.strip()
        else:
            combined_sort.append(s.strip())
    return combined_sort


def split_folder_glob(s):
    p = Path(s).resolve()

    if "*" not in s and not p.exists():
        p.mkdir(parents=True, exist_ok=True)

    if p.is_dir():
        return p, "*"
    return p.parent, p.name


def override_config(args, extractor_config):
    defaults = getattr(args, "defaults", None) or {}
    overridden_args = {k: v for k, v in args.__dict__.items() if defaults.get(k) != v}
    args_env = argparse.Namespace(
        **{**defaults, **(extractor_config.get("extractor_config") or {}), **extractor_config, **overridden_args}
    )
    return args_env


def args_override(namespace, kwargs):
    namespace_dict = copy(namespace.__dict__)
    namespace_dict.update(kwargs)
    return argparse.Namespace(**namespace_dict)


ops = {"<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne, ">=": operator.ge, ">": operator.gt}


def cmp(arg1, op, arg2):
    operation = ops.get(op)
    return operation(arg1, arg2)  # type: ignore


def dict_from_unknown_args(unknown_args):
    kwargs = {}
    key = None
    values = []

    def get_val():
        if len(values) == 1:
            return nums.safe_int_float_str(values[0])
        else:
            return " ".join(values)

    for arg in unknown_args:
        if arg.startswith("-"):
            if key is not None:
                kwargs[key] = get_val()  # previous values
                values.clear()
            # Process the new key
            key = arg.strip("-").replace("-", "_")
        else:
            values.append(arg)

    if len(values) > 0:
        kwargs[key] = get_val()

    return kwargs


def dict_of_lists_from_unknown_args(unknown_args):
    result = defaultdict(list)
    for i in range(len(unknown_args)):
        key = unknown_args[i]

        if key.startswith("-"):
            key = key.strip("-")
            if not unknown_args[i + 1].startswith("-"):
                result[key].append(unknown_args[i + 1])

    return result
