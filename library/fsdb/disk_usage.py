import os
from collections import defaultdict
from pathlib import Path

from library import usage
from library.fsdb import files_info
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, consts, file_utils, iterables, path_utils, processes, sqlgroups, strings


def parse_args(defaults_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage.disk_usage)
    arggroups.files(parser)
    arggroups.sql_fs(parser)
    parser.set_defaults(hide_deleted=True)
    arggroups.group_folders(parser)

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

    arggroups.files_post(args)
    arggroups.sql_fs_post(args)
    arggroups.group_folders_post(args)

    return args


def sort_by(args):
    if args.sort_groups_by:
        return lambda x: x.get(args.sort_groups_by.replace(" desc", "")) or 0

    return lambda x: (x.get("size") or 0 / (x.get("count") or 1), x.get("size") or 0, x.get("count") or 1)


def check_depth(args, p):
    if args.max_depth is not None:
        return args.min_depth <= len(p) <= args.max_depth
    else:
        return args.min_depth <= len(p)


def format_folder(p):
    p = str(p)
    if p != os.sep:
        return p + os.sep
    else:
        return p

def get_subset(args) -> list[dict]:
    all_paths = [d["path"] for d in args.data]
    tree = path_utils.DirTree(all_paths)

    d = {}
    for m in args.data:
        if args.cwd is not None and not m["path"].startswith(args.cwd):
            continue

        p = m["path"].split(os.sep)

        is_depth = check_depth(args, p)
        if is_depth:
            d[m["path"]] = m  # add file

        if args.parents:
            while p and check_depth(args, p):  # sum folder statistics
                p.pop()
                if p == [""]:
                    continue

                parent = os.sep.join(p)
                if parent not in d:
                    d[parent] = {"size": 0, "duration": 0, "count": 0}
                    d[parent]["folders"] = len(tree.recursive(parent))
                d[parent]["size"] += m.get("size") or 0
                d[parent]["duration"] += m.get("duration") or 0
                d[parent]["count"] += 1
        elif p and len(p) > 1:
            p.pop()
            if p != [""]:
                parent = os.sep.join(p)
                if parent not in d:
                    d[parent] = {"size": 0, "duration": 0, "count": 0}
                    d[parent]["folders"] = len(tree.immediate(parent))
                d[parent]["size"] += m.get("size") or 0
                d[parent]["duration"] += m.get("duration") or 0
                d[parent]["count"] += 1

    reverse = True
    if args.sort_groups_by and " desc" in args.sort_groups_by:
        reverse = False

    return sorted([{"path": format_folder(k), **v} for k, v in d.items()], key=sort_by(args), reverse=reverse)



def get_subset_group_by_extensions(args) -> list[dict]:
    d = {}
    for m in args.data:
        if args.cwd is not None and not m["path"].startswith(args.cwd):
            continue

        ext = path_utils.ext(m["path"])
        if ext not in d:
            d[ext] = {"size": 0, "duration": 0, "count": 0}
        d[ext]["size"] += m.get("size") or 0
        d[ext]["duration"] += m.get("duration") or 0
        d[ext]["count"] += 1

    reverse = True
    if args.sort_groups_by and " desc" in args.sort_groups_by:
        reverse = False

    return sorted([{"path": k, **v} for k, v in d.items()], key=sort_by(args), reverse=reverse)


def get_subset_group_by_mimetypes(args) -> list[dict]:
    d = {}
    for m in args.data:
        if args.cwd is not None and not m["path"].startswith(args.cwd):
            continue

        mimetype = file_utils.get_file_type(m)["type"]
        if mimetype not in d:
            d[mimetype] = {"size": 0, "duration": 0, "count": 0}
        d[mimetype]["size"] += m.get("size") or 0
        d[mimetype]["duration"] += m.get("duration") or 0
        d[mimetype]["count"] += 1

    reverse = True
    if args.sort_groups_by and " desc" in args.sort_groups_by:
        reverse = False

    return sorted([{"path": k, **v} for k, v in d.items()], key=sort_by(args), reverse=reverse)


def get_subset_group_by_size(args) -> list[dict]:
    d = {}
    for m in args.data:
        if args.cwd is not None and not m["path"].startswith(args.cwd):
            continue

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

    return list(reversed([{"path": k, **v} for k, v in d.items() if v["count"] > 0]))


def filter_criteria(args, media):
    if args.folders_only:
        media = [d for d in media if d.get("count")]
    elif args.files_only:
        media = [d for d in media if not d.get("count")]

    if args.folder_sizes:
        media = [d for d in media if args.folder_sizes(d.get("size"))]
    if args.file_counts:
        media = [d for d in media if args.file_counts(d.get("count"))]
    if args.folder_counts:
        media = [d for d in media if args.folder_counts(d.get("folders"))]

    return media


def load_subset(args):
    if args.group_by_size:
        args.subset = get_subset_group_by_size(args)
    elif args.group_by_extensions:
        args.subset = get_subset_group_by_extensions(args)
    elif args.group_by_mimetypes:
        args.subset = get_subset_group_by_mimetypes(args)
    elif len(args.data) <= 2:
        args.subset = args.data
    elif not args.depth:
        while len(args.subset) < 2:
            args.min_depth += 1
            args.subset = get_subset(args)
            args.subset = filter_criteria(args, args.subset)  # check within loop to avoid "no media"
    else:
        args.subset = get_subset(args)

    args.subset = filter_criteria(args, args.subset)

    if not args.subset:
        processes.no_media_found()

    args.cwd = os.sep.join(args.subset[0]["path"].split(os.sep)[: args.min_depth - 1]) + os.sep
    return args.cwd, args.subset


def get_data(args) -> list[dict]:
    if args.database:
        media = list(args.db.query(*sqlgroups.fs_sql(args, limit=None)))
    else:
        if args.hide_deleted:
            args.paths = [p for p in args.paths if os.path.exists(p)]
        media = file_utils.gen_d(args)

        media = files_info.filter_files_by_criteria(args, media)
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

    summary = iterables.list_dict_summary(args.subset)
    if args.limit and not "a" in args.print:
        args.subset = args.subset[: args.limit]

    if args.group_by_extensions:
        units = "file extensions"
    elif args.group_by_mimetypes:
        units = "file types"
    elif args.group_by_size:
        units = "file sizes"
    else:
        units = f"paths at depth {args.min_depth} ({num_folders} folders, {num_files} files)"

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
