import argparse, operator, random
from collections import defaultdict
from copy import copy
from pathlib import Path

from xklb.utils import consts, file_utils, iterables, nums, processes, strings
from xklb.utils.consts import SC


def gen_paths(args, default_exts=None):
    if args.paths is None:
        processes.exit_error("No paths passed in")

    if args.from_json:
        for path in args.paths:
            json_data = strings.safe_json_loads(path)
            if isinstance(json_data, list):
                for json_item in json_data:
                    yield json_item["path"]
            elif isinstance(json_data, dict):
                yield json_data["path"]
            else:
                raise TypeError
    else:
        for path in args.paths:
            if path.strip():
                p = Path(path)
                if p.is_dir():
                    yield from file_utils.rglob(str(p), args.ext or default_exts, getattr(args, "exclude", None))[0]
                else:
                    yield path


def gen_d(args, default_exts=None):
    if args.paths is None:
        processes.exit_error("No data passed in")

    if args.from_json:
        for path in args.paths:
            json_data = strings.safe_json_loads(path)
            if isinstance(json_data, list):
                for json_item in json_data:
                    yield json_item
            elif isinstance(json_data, dict):
                yield json_data
            else:
                raise TypeError
    else:
        for path in args.paths:
            if path.strip():
                p = Path(path)
                if p.is_dir():
                    for sp in file_utils.rglob(str(p), args.ext or default_exts, getattr(args, "exclude", None))[0]:
                        yield {"path": sp}
                else:
                    yield {"path": path}


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


def parse_args_sort(args, columns, table_prefix="m.") -> tuple[str, list[str]]:
    sort_list = []
    select_list = []
    if args.sort:
        combined_sort = parse_ambiguous_sort(args.sort)

        for s in combined_sort:
            if s.startswith("same-"):
                var = s[len("same-") :]
                direction = "DESC"
                if var.lower().endswith((" asc", " desc")):
                    var, direction = var.split(" ")

                select_list.append(
                    f"CASE WHEN {var} IS NULL THEN NULL ELSE COUNT(*) OVER (PARTITION BY {var}) END AS same_{var}_count",
                )
                sort_list.append(f"same_{var}_count {direction}")
            else:
                sort_list.append(s)

    # switching between videos with and without subs is annoying
    subtitle_count = "=0"
    if random.random() < getattr(args, "subtitle_mix", consts.DEFAULT_SUBTITLE_MIX):
        # bias slightly toward videos without subtitles
        subtitle_count = ">0"

    sorts = [
        "play_count" if "play_count" in sort_list else None,
        "random" if getattr(args, "random", False) else None,
        "rank" if sort_list and "rank" in sort_list else None,
        "video_count > 0 desc" if "video_count" in columns and args.action == SC.watch else None,
        "audio_count > 0 desc" if "audio_count" in columns else None,
        table_prefix + 'path like "http%"',
        "width < height desc" if "width" in columns and getattr(args, "portrait", False) else None,
        (
            f"subtitle_count {subtitle_count} desc"
            if "subtitle_count" in columns
            and args.action == SC.watch
            and not any(
                [
                    args.print,
                    consts.PYTEST_RUNNING,
                    "subtitle_count" in " ".join(args.where),
                    args.limit != consts.DEFAULT_PLAY_QUEUE,
                ],
            )
            else None
        ),
        *(sort_list or []),
        "play_count, playhead desc, time_last_played" if args.action in (SC.media, SC.listen, SC.watch) else None,
        "duration desc" if args.action in (SC.media, SC.listen, SC.watch) and args.include else None,
        "size desc" if args.action in (SC.media, SC.listen, SC.watch) and args.include else None,
        table_prefix + "title IS NOT NULL desc" if "title" in columns else None,
        table_prefix + "path",
    ]

    sort = list(filter(bool, sorts))
    sort = [override_sort(s) for s in sort]
    sort = ",".join(sort)
    return sort.replace(",,", ","), select_list


def parse_args_limit(args):
    if not args.limit:
        if not any(
            [
                args.print and len(args.print.replace("p", "")) > 0,
                getattr(args, "partial", False),
                getattr(args, "lower", False),
                getattr(args, "upper", False),
            ],
        ):
            if args.action in (SC.media, SC.listen, SC.watch, SC.read):
                args.limit = consts.DEFAULT_PLAY_QUEUE
            elif args.action in (SC.view,):
                args.limit = consts.DEFAULT_PLAY_QUEUE * 4
            elif args.action in (SC.history,):
                args.limit = 10
            elif args.action in (SC.links_open,):
                args.limit = consts.MANY_LINKS - 1
            elif args.action in (SC.download,):
                args.limit = consts.DEFAULT_PLAY_QUEUE * 60
    elif args.limit.lower() in ("inf", "all"):
        args.limit = None
    else:
        args.limit = int(args.limit)


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
