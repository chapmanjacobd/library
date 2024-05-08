import argparse
from pathlib import Path

import humanize
from tabulate import tabulate

from xklb import usage
from xklb.folders import big_dirs
from xklb.text import cluster_sort
from xklb.utils import arg_utils, arggroups, argparse_utils, consts, file_utils, nums, path_utils, printing, strings
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.similar_folders)
    arggroups.group_folders(parser)
    arggroups.cluster(parser)

    parser.add_argument("--small", "--reverse", action="store_true")
    parser.add_argument("--only-duplicates", action="store_true")
    parser.add_argument("--only-originals", action="store_true")

    parser.add_argument(
        "--full-path", action="store_true", help="Cluster using full path instead of just the parent folder name"
    )
    parser.add_argument("--estimated-duplicates", "--dupes", type=float)

    parser.add_argument("--total-sizes", action="store_true", help="Compare total size instead of median size")
    parser.add_argument(
        "--total-durations", action="store_true", help="Compare total duration instead of median duration"
    )
    parser.add_argument("--sizes-delta", "--size-delta", type=float, default=10.0)
    parser.add_argument("--counts-delta", "--count-delta", type=float, default=3.0)
    parser.add_argument("--durations-delta", "--duration-delta", type=float, default=5.0)

    parser.add_argument("--filter-names", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--filter-sizes", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--filter-durations", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--filter-counts", action=argparse.BooleanOptionalAction, default=True)

    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    args.action = consts.SC.similar_folders
    arggroups.args_post(args, parser)

    arggroups.group_folders_post(args)

    if not args.filter_counts:
        args.counts_delta = 200.0
    if not args.filter_sizes:
        args.sizes_delta = 200.0
    if not args.filter_durations:
        args.duration_delta = 200.0

    if not args.filter_names and not args.filter_counts and not args.filter_sizes and not args.filter_durations:
        print("Nothing to do")
        raise NotImplementedError

    arggroups.sql_fs_post(args)
    arggroups.group_folders_post(args)

    return args


def map_and_name(media, clusters):
    bound_dicts = cluster_sort.map_cluster_to_paths(media, clusters)

    result = []
    for _cluster_id, dicts in bound_dicts.items():
        paths = sorted(d["path"] for d in dicts)
        common_path = path_utils.common_path(paths)
        metadata = {"common_path": common_path, "grouped_paths": dicts}
        result.append(metadata)
    return result


def cluster_folders(args, media):
    if len(media) < 2:
        return media

    n_clusters = args.clusters
    if args.estimated_duplicates:
        n_clusters = int(len(media) / args.estimated_duplicates)

    if args.full_path:
        sentence_strings = (strings.path_to_sentence(d["path"]) for d in media)
    else:
        sentence_strings = (strings.path_to_sentence(Path(d["path"]).name) for d in media)

    clusters = cluster_sort.find_clusters(n_clusters, sentence_strings, stop_words=args.stop_words)
    groups = map_and_name(media, clusters)

    return groups


def is_same_group(args, m0, m):
    count_diff = nums.percentage_difference(m0["exists"], m["exists"])
    if args.total_sizes:
        size_diff = nums.percentage_difference(m0["size"], m["size"])
    else:
        size_diff = nums.percentage_difference(m0["median_size"], m["median_size"])

    if args.total_durations:
        duration_diff = nums.percentage_difference(m0["duration"], m["duration"])
    else:
        duration_diff = nums.percentage_difference(m0["median_duration"], m["median_duration"])

    return size_diff < args.sizes_delta and count_diff < args.counts_delta and duration_diff < args.durations_delta


def cluster_by_numbers(args, media):
    group_id = 0
    temp_groups = []
    media_groups = []
    for m in media:
        grouped = False
        for i, group in enumerate(temp_groups):
            m0 = group[0]
            if is_same_group(args, m0, m):
                group.append(m)
                media_groups.append(i)
                grouped = True
                break

        if not grouped:
            temp_groups.append([m])
            media_groups.append(group_id)
            group_id += 1

    assert len(media_groups) == len(media)
    return media_groups


def filter_group_by_numbers(args, group):
    media = group["grouped_paths"]

    output = []
    m0 = media[0]
    for m in media[1:]:
        if is_same_group(args, m0, m):
            output.append(m)

    if output:
        group["grouped_paths"] = [m0] + output
        return group
    else:
        return None


def filter_groups_by_numbers(args, groups):
    groups = [filter_group_by_numbers(args, group) for group in groups]
    groups = [group for group in groups if group]
    return groups


def similar_folders():
    args = parse_args()
    media = arg_utils.gen_d(args)
    media = [d if "size" in d else file_utils.get_filesize(d) for d in media]
    media = big_dirs.group_files_by_parent(args, media)
    if args.folder_sizes:
        media = [d for d in media if args.folder_sizes(d["size"])]

    if args.filter_sizes or args.filter_counts or args.filter_durations:
        clusters = cluster_by_numbers(args, media)
        groups = map_and_name(media, clusters)
        log.info("Folder size/duration/count clustering sorted %s folders into %s groups", len(media), len(groups))
        single_folder_groups = [d for d in groups if len(d["grouped_paths"]) == 1]
        groups = [d for d in groups if len(d["grouped_paths"]) > 1]
        log.info("Filtered out %s single-folder groups", len(single_folder_groups))
        log.debug(single_folder_groups)

        if args.filter_names:
            media = [d for group in groups for d in group["grouped_paths"]]

    if args.filter_names:
        groups = cluster_folders(args, media)
        groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_path"])))
        log.info("Name clustering sorted %s folders into %s groups", len(media), len(groups))

        if args.filter_sizes or args.filter_counts or args.filter_durations:
            prev_count = len(groups)
            groups = filter_groups_by_numbers(args, groups)  # effectively a second pass
            log.info("(2nd pass) group size/duration/count filtering removed %s groups", prev_count - len(groups))

    if not args.only_originals and not args.only_duplicates:
        print("Duplicate groups:")

    for group in groups:
        media = group["grouped_paths"]
        media = sorted(media, key=lambda d: d["size"], reverse=not args.small)

        if args.only_originals:
            media = media[:1]
        if args.only_duplicates:
            media = media[1:]

        if "f" in args.print:
            for d in media:
                printing.pipe_print(d["path"])
        else:
            print(
                tabulate(
                    [
                        {
                            f'group {group["common_path"]}': d["path"],
                            "total_size": humanize.naturalsize(d["size"], binary=True),
                            "median_size": humanize.naturalsize(d["median_size"], binary=True),
                            "total_duration": printing.human_duration(d["duration"]),
                            "median_duration": printing.human_duration(d["median_duration"]),
                            "median_size": humanize.naturalsize(d["median_size"], binary=True),
                            "files": d["exists"],
                        }
                        for d in media
                    ],
                    tablefmt=consts.TABULATE_STYLE,
                    headers="keys",
                    showindex=False,
                )
            )

        if not args.only_originals and not args.only_duplicates:
            print()

    if not args.only_originals and not args.only_duplicates:
        print(len(groups), "groups found")
