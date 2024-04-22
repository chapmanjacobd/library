import argparse, os
from pathlib import Path

from xklb import media_printer, usage
from xklb.utils import arggroups, consts, db_utils, file_utils, nums, objects, processes, sql_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library disk_usage",
        usage=usage.disk_usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arggroups.sql_fs(parser)
    arggroups.operation_group_folders(parser)
    parser.set_defaults(limit="4000", depth=0)

    parser.add_argument("--folders-only", "-td", action="store_true", help="Only print folders")
    parser.add_argument("--files-only", "-tf", action="store_true", help="Only print files")

    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("working_directory", nargs="*", default=os.sep)
    args = parser.parse_intermixed_args()
    args.db = db_utils.connect(args)

    args.include += args.working_directory
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if len(args.include) == 1 and os.sep in args.include[0]:
        args.include = [file_utils.resolve_absolute_path(args.include[0])]

    if args.sort_groups_by:
        args.sort_groups_by = " ".join(args.sort_groups_by)

    if args.size:
        args.size = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", args.size)

    args.action = consts.SC.disk_usage
    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def sort_by(args):
    if args.sort_groups_by:
        return lambda x: x.get(args.sort_groups_by) or 0

    return lambda x: (x["size"] / (x.get("count") or 1), x["size"], x.get("count") or 1)


def get_subset(args, level=None, prefix=None) -> list[dict]:
    d = {}
    excluded_files = set()

    for m in args.data:
        if prefix is not None and not m["path"].startswith(prefix):
            continue

        p = m["path"].split(os.sep)
        if level is not None and len(p) == level and not m["path"].endswith(os.sep):
            d[m["path"]] = m

        while len(p) >= 2:
            p.pop()
            if p == [""]:
                continue

            parent = os.sep.join(p) + os.sep
            if level is not None and len(p) != level:
                excluded_files.add(parent)

            if parent not in d:
                d[parent] = {"size": 0, "count": 0}
            d[parent]["size"] += m.get("size") or 0
            d[parent]["count"] += 1

    reverse = True
    if args.sort_groups_by and " desc" in args.sort_groups_by:
        args.sort_groups_by = args.sort_groups_by.replace(" desc", "")
        reverse = False

    return sorted(
        [{"path": k, **v} for k, v in d.items() if k not in excluded_files],
        key=sort_by(args),
        reverse=reverse,
    )


def load_subset(args):
    level = args.depth
    if args.depth == 0:
        while len(args.subset) < 2:
            level += 1
            args.subset = get_subset(args, level=level, prefix=args.cwd)
    else:
        args.subset = get_subset(args, level=level, prefix=args.cwd)

    if not args.subset:
        processes.no_media_found()

    args.cwd = os.sep.join(args.subset[0]["path"].split(os.sep)[: level - 1]) + os.sep
    return args.cwd, args.subset


def get_data(args) -> list[dict]:
    m_columns = db_utils.columns(args, "media")
    args.filter_sql = []
    args.filter_bindings = {}

    if args.size:
        args.filter_sql.append(" and size IS NOT NULL " + args.size)
    db_utils.construct_search_bindings(
        args,
        [f"{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
    )

    media = list(
        args.db.query(
            f"""
        SELECT
            path
            , size
        FROM media m
        WHERE 1=1
            and size > 0
            {'and coalesce(time_deleted, 0) = 0' if 'time_deleted' in m_columns else ''}
            {'and coalesce(is_dir, 0) = 0' if 'is_dir' in m_columns else ''}
            {" ".join(args.filter_sql)}
        ORDER BY path
        """,
            args.filter_bindings,
        ),
    )

    if not media:
        processes.no_media_found()
    return media


def disk_usage():
    args = parse_args()
    args.data = get_data(args)
    args.subset = []
    args.cwd = None

    load_subset(args)

    num_folders = sum(1 for d in args.subset if d.get("count"))
    num_files = sum(1 for d in args.subset if not d.get("count"))

    if args.folders_only:
        args.subset = [d for d in args.subset if d.get("count")]
    elif args.files_only:
        args.subset = [d for d in args.subset if not d.get("count")]

    media_printer.media_printer(
        args,
        args.subset,
        units=f"paths at current depth ({num_folders} folders, {num_files} files)",
    )


if __name__ == "__main__":
    disk_usage()