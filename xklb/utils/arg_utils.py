import argparse, operator, random, sqlite3
from pathlib import Path

from xklb.utils import arggroups, consts, db_utils, file_utils, iterables
from xklb.utils.consts import SC


def is_sqlite(path):
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\000"
    except OSError:
        return False


def gen_paths(args):
    if args.paths_from_text:
        for path in args.paths:
            with open(path) as f:
                for line in f:
                    line = line.rstrip("\n")
                    if line.strip():
                        yield line
    elif args.paths_from_dbs or args.titles_from_dbs:
        for path in args.paths:
            if is_sqlite(path):
                s_db = db_utils.connect(args, conn=sqlite3.connect(path))
                m_columns = s_db["media"].columns_dict
                yield from (
                    d["path"]
                    for d in s_db.query(
                        f"""
                    SELECT
                        {'title AS path' if args.titles_from_dbs else 'path'}
                    FROM media
                    WHERE 1=1
                    {'and COALESCE(time_deleted,0) = 0' if 'time_deleted' in m_columns else ''}
                    """
                    )
                )
            else:
                print("Skipping non-SQLite file:", path)
    else:
        is_large = len(args.paths) > 1000
        for path in args.paths:
            if path.strip():
                if is_large:
                    yield path
                else:
                    p = Path(path)
                    if p.is_dir():
                        yield from file_utils.rglob(str(p), args.ext or None)[0]
                    else:
                        yield path


def d_from_path(path):
    try:
        stat = Path(path).stat()
        return {"path": str(path), "size": stat.st_size}
    except FileNotFoundError:
        print("Skipping non-existent file:", path)


def gen_d(args):
    if args.paths_from_text:
        for path in args.paths:
            with open(path) as f:
                for line in f:
                    line = line.rstrip("\n")
                    if line.strip():
                        d = d_from_path(line)
                        if d:
                            yield d
    elif args.paths_from_dbs or args.titles_from_dbs:
        for path in args.paths:
            if is_sqlite(path):
                sdb = db_utils.connect(args, conn=sqlite3.connect(path))
                m_columns = sdb["media"].columns_dict
                yield from sdb.query(
                    f"""
                    SELECT
                        path
                        {', size' if 'size' in m_columns else ''}
                        {', title' if 'title' in m_columns else ''}
                    FROM media
                    WHERE 1=1
                    {'AND COALESCE(time_deleted,0) = 0' if 'time_deleted' in m_columns else ''}
                    {'AND size is NOT NULL' if 'size' in m_columns else ''}
                    """
                )
            else:
                print("Skipping non-SQLite file:", path)
    else:
        for path in args.paths:
            if path.strip():
                p = Path(path)
                if p.is_dir():
                    for sp in file_utils.rglob(str(p), args.ext or None)[0]:
                        d = d_from_path(sp)
                        if d:
                            yield d
                else:
                    d = d_from_path(p)
                    if d:
                        yield d


def stdarg():
    parser = argparse.ArgumentParser()
    arggroups.paths_or_stdin(parser)
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
        .replace("priorityfast", "ntile(1000) over (order by size) desc, duration")
        .replace("priority", "ntile(1000) over (order by size/duration) desc")
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
        (
            f"subtitle_count {subtitle_count} desc"
            if "subtitle_count" in m_columns
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
            elif args.action in (SC.links_open):
                args.limit = consts.MANY_LINKS - 1
            elif args.action in (SC.download):
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


def override_config(parser, extractor_config, args):
    default_args = {key: parser.get_default(key) for key in vars(args)}
    overridden_args = {k: v for k, v in args.__dict__.items() if default_args.get(k) != v}
    args_env = argparse.Namespace(**{**default_args, **extractor_config, **overridden_args})
    return args_env


def kwargs_overwrite(namespace, kwargs):
    namespace_dict = vars(namespace)
    namespace_dict.update(kwargs)
    return argparse.Namespace(**namespace_dict)


ops = {"<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne, ">=": operator.ge, ">": operator.gt}


def cmp(arg1, op, arg2):
    operation = ops.get(op)
    return operation(arg1, arg2)  # type: ignore
