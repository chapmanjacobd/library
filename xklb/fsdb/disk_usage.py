import argparse, os

from xklb import media_printer, usage
from xklb.utils import arggroups, argparse_utils, consts, processes, sqlgroups


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(
        prog="library disk_usage",
        usage=usage.disk_usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arggroups.sql_fs(parser)
    arggroups.group_folders(parser)
    parser.set_defaults(limit="4000", depth=0)

    parser.add_argument("--folders-only", "-td", action="store_true", help="Only print folders")
    parser.add_argument("--files-only", "-tf", action="store_true", help="Only print files")

    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*", default=os.sep)
    args = parser.parse_intermixed_args()
    args.action = consts.SC.disk_usage
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    arggroups.group_folders_post(args)

    return args


def sort_by(args):
    if args.sort_groups_by:
        return lambda x: x.get(args.sort_groups_by.replace(" desc", "")) or 0

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
    media = list(args.db.query(*sqlgroups.fs_sql(args)))

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
