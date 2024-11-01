import os

from xklb import usage
from xklb.playback import media_printer
from xklb.utils import arg_utils, arggroups, argparse_utils, file_utils, path_utils, processes, sqlgroups


def parse_args(defaults_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage.disk_usage)
    arggroups.sql_fs(parser)
    parser.set_defaults(hide_deleted=True)
    arggroups.group_folders(parser)
    parser.set_defaults(limit="4000", depth=0)

    parser.add_argument("--folders-only", "-td", action="store_true", help="Only print folders")
    parser.add_argument("--files-only", "-tf", action="store_true", help="Only print files")

    parser.add_argument("--group-by-extensions", action="store_true", help="Print statistics about file extensions")

    arggroups.debug(parser)

    arggroups.database_or_paths(parser)
    parser.set_defaults(**(defaults_override or {}))
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    arggroups.group_folders_post(args)

    return args


def sort_by(args):
    if args.sort_groups_by:
        return lambda x: x.get(args.sort_groups_by.replace(" desc", "")) or 0

    return lambda x: (x.get("size") or 0 / (x.get("count") or 1), x.get("size") or 0, x.get("count") or 1)


def get_subset(args, level=None, prefix=None) -> list[dict]:
    d = {}
    excluded_files = set()

    for m in args.data:
        if prefix is not None and not m["path"].startswith(prefix):
            continue

        p = m["path"].split(os.sep)
        if level is not None and len(p) == level and not m["path"].endswith(os.sep):
            d[m["path"]] = m

        if args.group_by_extensions:
            ext = path_utils.ext(m["path"])
            if ext not in d:
                d[ext] = {"size": 0, "count": 0}
            d[ext]["size"] += m.get("size") or 0
            d[ext]["count"] += 1
        else:
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
    if not args.group_by_extensions and args.depth == 0:
        while len(args.subset) < 2:
            args.depth += 1
            args.subset = get_subset(args, level=args.depth, prefix=args.cwd)
    else:
        args.subset = get_subset(args, level=args.depth, prefix=args.cwd)

    if not args.subset:
        processes.no_media_found()

    args.cwd = os.sep.join(args.subset[0]["path"].split(os.sep)[: args.depth - 1]) + os.sep
    return args.cwd, args.subset


def get_data(args) -> list[dict]:
    if args.database:
        media = list(args.db.query(*sqlgroups.fs_sql(args, limit=None)))
    else:
        if args.hide_deleted:
            args.paths = [p for p in args.paths if os.path.exists(p)]
        media = arg_utils.gen_d(args)
        media = [d if "size" in d else file_utils.get_filesize(d) for d in media]

    if not media:
        processes.no_media_found()
    return media


def disk_usage(defaults_override=None):
    args = parse_args(defaults_override)
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

    args.subset = args.subset[: args.limit]

    media_printer.media_printer(
        args,
        args.subset,
        units=(
            f"file extensions"
            if args.group_by_extensions
            else f"paths at depth {args.depth} ({num_folders} folders, {num_files} files)"
        ),
    )


def extensions():
    disk_usage({"group_by_extensions": True})


if __name__ == "__main__":
    disk_usage()
