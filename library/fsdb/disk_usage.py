import os

from library import usage
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, file_utils, iterables, path_utils, processes, sqlgroups, strings


def parse_args(defaults_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage.disk_usage)
    arggroups.sql_fs(parser)
    parser.set_defaults(hide_deleted=True)
    arggroups.group_folders(parser)
    parser.set_defaults(limit="4000", depth=0)

    parser.add_argument("--folders-only", "-td", action="store_true", help="Only print folders")
    parser.add_argument("--files-only", "-tf", action="store_true", help="Only print files")

    parser.add_argument("--group-by-extensions", action="store_true", help="Print statistics about file extensions")
    parser.add_argument(
        "--group-by-mimetypes", "--group-by-type", action="store_true", help="Print statistics about file types"
    )
    parser.add_argument("--group-by-size", action="store_true", help="Print statistics about file size")

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
                d[ext] = {"size": 0, "duration": 0, "count": 0}
            d[ext]["size"] += m.get("size") or 0
            d[ext]["duration"] += m.get("duration") or 0
            d[ext]["count"] += 1
        elif args.group_by_mimetypes:
            mimetype = file_utils.get_file_type(m)["type"]
            if mimetype not in d:
                d[mimetype] = {"size": 0, "duration": 0, "count": 0}
            d[mimetype]["size"] += m.get("size") or 0
            d[mimetype]["duration"] += m.get("duration") or 0
            d[mimetype]["count"] += 1
        elif args.group_by_size:
            base_edges = [2, 5, 10]
            multipliers = base_edges + [n * 10 for n in base_edges] + [n * 100 for n in base_edges]

            unit_multiplier = 1024
            units = [
                1,
                unit_multiplier,
                unit_multiplier**2,
                unit_multiplier**3,
                unit_multiplier**4,
            ]  # Bytes, KB, MB, GB, TB

            bin_edges = [0.0]
            for unit in units:
                for m_mult in multipliers:
                    bin_edges.append(float(m_mult * unit))
            bin_edges.append(float("inf"))

            file_size = m.get("size") or 0
            for i in range(len(bin_edges) - 1):
                lower_bound = bin_edges[i]
                upper_bound = bin_edges[i + 1]
                bin_label = f"{strings.file_size(lower_bound)}-{strings.file_size(upper_bound)}"
                if bin_label not in d:
                    d[bin_label] = {"size": 0, "duration": 0, "count": 0}

                if lower_bound <= file_size < upper_bound:
                    d[bin_label]["size"] += file_size
                    d[bin_label]["duration"] += m.get("duration") or 0
                    d[bin_label]["count"] += 1
                    break
        else:
            while len(p) >= 2:
                p.pop()
                if p == [""]:
                    continue

                parent = os.sep.join(p) + os.sep
                if level is not None and len(p) != level:
                    excluded_files.add(parent)

                if parent not in d:
                    d[parent] = {"size": 0, "duration": 0, "count": 0}
                d[parent]["size"] += m.get("size") or 0
                d[parent]["duration"] += m.get("duration") or 0
                d[parent]["count"] += 1

    if args.group_by_size:
        return list(reversed([{"path": k, **v} for k, v in d.items() if v["count"] > 0]))

    reverse = True
    if args.sort_groups_by and " desc" in args.sort_groups_by:
        reverse = False

    return sorted(
        [{"path": k, **v} for k, v in d.items() if k not in excluded_files],
        key=sort_by(args),
        reverse=reverse,
    )


def load_subset(args):
    if any([args.group_by_extensions, args.group_by_mimetypes, args.group_by_size]):
        args.subset = get_subset(args, level=args.depth, prefix=args.cwd)
    elif len(args.data) <= 2:
        args.subset = args.data
    elif args.depth == 0:
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
        media = file_utils.gen_d(args)
        media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]

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

    summary = iterables.list_dict_summary(args.subset)
    args.subset = args.subset[: args.limit]

    if args.group_by_extensions:
        units = "file extensions"
    elif args.group_by_mimetypes:
        units = "file types"
    elif args.group_by_size:
        units = "file sizes"
    else:
        units = f"paths at depth {args.depth} ({num_folders} folders, {num_files} files)"

    media_printer.media_printer(args, args.subset, units=units)
    if not args.to_json:
        for d in summary:
            if "count" in d:
                print(f"{d['path']}={strings.file_size(d['size'])} count={d['count']}")


def extensions():
    disk_usage({"group_by_extensions": True})


def mimetypes():
    disk_usage({"group_by_mimetypes": True})


def sizes():
    disk_usage({"group_by_size": True})
