import argparse, operator, random, sys
from ast import literal_eval
from pathlib import Path

from xklb.utils import consts, db_utils, iterables
from xklb.utils.consts import SC
from xklb.utils.iterables import flatten

STDIN_DASH = ["-"]


class ArgparseList(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None) or []

        if isinstance(values, str):
            items.extend(values.split(","))  # type: ignore
        else:
            items.extend(flatten(s.split(",") for s in values))  # type: ignore

        setattr(namespace, self.dest, items)


class ArgparseDict(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        try:
            d = {}
            k_eq_v = list(flatten([val.split(" ") for val in values]))
            for s in k_eq_v:
                k, v = s.split("=", 1)
                if any(sym in v for sym in (" [", " {")):
                    d[k] = literal_eval(v)
                elif v.strip() in ("True", "False"):
                    d[k] = bool(v.strip())
                else:
                    d[k] = v

        except ValueError as ex:
            msg = f'Could not parse argument "{values}" as k1=1 k2=2 format {ex}'
            raise argparse.ArgumentError(self, msg) from ex
        setattr(args, self.dest, d)


class ArgparseArgsOrStdin(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values == STDIN_DASH:
            lines = sys.stdin.readlines()
            if not lines or (len(lines) == 1 and lines[0].strip() == ""):
                lines = None
            else:
                lines = [s.strip() for s in lines]
        else:
            lines = values
        setattr(namespace, self.dest, lines)


def is_sqlite(path):
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\000"
    except IOError:
        return False


def gen_paths(args):
    if args.file:
        with open(args.file, "r") as f:
            for line in f:
                path = line.rstrip("\n")
                if path.strip():
                    yield path
    else:
        for path in args.paths:
            if path.strip():
                yield path


def stdarg():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", "-f", help="File with one URL per line")
    parser.add_argument("paths", nargs="*", default=STDIN_DASH, action=ArgparseArgsOrStdin)
    args = parser.parse_args()
    return gen_paths(args)


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
        .replace("priority", "ntile(1000) over (order by size) desc, duration")
    )


def parse_ambiguous_sort(sort):
    combined_sort = []
    for s in iterables.flatten([s.split(",") for s in sort]):
        if s.strip() in ["asc", "desc"] and combined_sort:
            combined_sort[-1] += " " + s.strip()
        else:
            combined_sort.append(s.strip())
    return combined_sort


def parse_args_sort(args) -> None:
    if args.sort:
        combined_sort = parse_ambiguous_sort(args.sort)

        sort_list = []
        select_list = []
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

        args.sort = sort_list
        args.select = select_list
    elif not args.sort and hasattr(args, "defaults"):
        args.defaults.append("sort")

    m_columns = db_utils.columns(args, "media")

    # switching between videos with and without subs is annoying
    subtitle_count = "=0"
    if random.random() < getattr(args, "subtitle_mix", consts.DEFAULT_SUBTITLE_MIX):
        # bias slightly toward videos without subtitles
        subtitle_count = ">0"

    sorts = [
        "random" if getattr(args, "random", False) else None,
        "rank" if args.sort and "rank" in args.sort else None,
        "video_count > 0 desc" if "video_count" in m_columns and args.action == SC.watch else None,
        "audio_count > 0 desc" if "audio_count" in m_columns else None,
        'm.path like "http%"',
        "width < height desc" if "width" in m_columns and getattr(args, "portrait", False) else None,
        f"subtitle_count {subtitle_count} desc"
        if "subtitle_count" in m_columns
        and args.action == SC.watch
        and not any(
            [
                args.print,
                consts.PYTEST_RUNNING,
                "subtitle_count" in args.where,
                args.limit != consts.DEFAULT_PLAY_QUEUE,
            ],
        )
        else None,
        *(args.sort or []),
        "duration desc" if args.action in (SC.listen, SC.watch) and args.include else None,
        "size desc" if args.action in (SC.listen, SC.watch) and args.include else None,
        "play_count" if args.action in (SC.listen, SC.watch) else None,
        "m.title IS NOT NULL desc" if "title" in m_columns else None,
        "m.path",
        "random",
    ]

    sort = list(filter(bool, sorts))
    sort = [override_sort(s) for s in sort]
    sort = "\n        , ".join(sort)
    args.sort = sort.replace(",,", ",")


def parse_args_limit(args):
    if not args.limit:
        args.defaults.append("limit")
        if not any(
            [
                args.print and len(args.print.replace("p", "")) > 0,
                getattr(args, "partial", False),
                getattr(args, "lower", False),
                getattr(args, "upper", False),
            ],
        ):
            if args.action in (SC.listen, SC.watch, SC.read):
                args.limit = consts.DEFAULT_PLAY_QUEUE
            elif args.action in (SC.view):
                args.limit = consts.DEFAULT_PLAY_QUEUE * 4
            elif args.action in (SC.open_links):
                args.limit = consts.MANY_LINKS - 1
            elif args.action in (SC.download):
                args.limit = consts.DEFAULT_PLAY_QUEUE * 60
    elif args.limit.lower() in ("inf", "all"):
        args.limit = None


def split_folder_glob(s):
    p = Path(s).resolve()

    if "*" not in s and not p.exists():
        p.mkdir(parents=True, exist_ok=True)

    if p.is_dir():
        return p, "*"
    return p.parent, p.name


def override_config(parser, extractor_config, args):
    default_args = {key: parser.get_default(key) for key in vars(args)}
    overridden_args = {k: v for k, v in args.__dict__.items() if default_args.get(k) != v}
    args_env = argparse.Namespace(**{**default_args, **extractor_config, **overridden_args})
    return args_env


ops = {"<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne, ">=": operator.ge, ">": operator.gt}


def cmp(arg1, op, arg2):
    operation = ops.get(op)
    return operation(arg1, arg2)
