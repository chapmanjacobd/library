import argparse
from pathlib import Path

import humanize

from xklb import usage
from xklb.text import cluster_sort
from xklb.utils import arg_utils, arggroups, strings


def parse_args():
    parser = argparse.ArgumentParser(usage=usage.similar_files)
    arggroups.operation_cluster(parser)
    parser.add_argument("--small", "--reverse", "-r", action="store_true")
    parser.add_argument("--print-size", "--size", action="store_true")
    parser.add_argument("--only-duplicates", action="store_true")
    parser.add_argument("--only-originals", action="store_true")
    parser.add_argument("--estimated-duplicates", "--dupes", type=float)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()

    return args


def cluster_filenames(paths, n_clusters=None, stop_words=None):
    if len(paths) < 2:
        return paths

    sentence_strings = (strings.path_to_sentence(Path(s).name) for s in paths)
    clusters = cluster_sort.find_clusters(n_clusters, sentence_strings, stop_words=stop_words)
    result = cluster_sort.map_and_name(paths, clusters)

    return result


def similar_files():
    args = parse_args()
    paths = [str(p) for p in arg_utils.gen_paths(args)]  # TODO: change to gen_d

    n_clusters = args.clusters
    if args.estimated_duplicates:
        n_clusters = int(len(paths) / args.estimated_duplicates)

    groups = cluster_filenames(paths, n_clusters=n_clusters)
    groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_path"])))  # type: ignore

    if not args.only_originals and not args.only_duplicates:
        print("Duplicate groups:")

    for group in groups:
        t = [(path, Path(path).stat().st_size) for path in group["grouped_paths"]]  # type: ignore
        t = sorted(t, key=lambda x: x[1], reverse=not args.small)

        if args.only_originals:
            t = t[:1]
        if args.only_duplicates:
            t = t[1:]

        for path, size in t:
            if args.print_size:
                print(path, "# ", humanize.naturalsize(size, binary=True))
            else:
                print(path)

        # TODO:
        # if "f" in args.print:
        #     for d in media:
        #         printing.pipe_print(d["path"])
        # else:
        #     print(
        #         tabulate(
        #             [
        #                 {
        #                     f'group {group["common_path"]}': d['path'],
        #                     'total_size': humanize.naturalsize(d["size"], binary=True),
        #                     'median_size': humanize.naturalsize(d["median_size"], binary=True),
        #                     'files':d['exists'],
        #                 }
        #                 for d in media
        #             ],
        #             tablefmt=consts.TABULATE_STYLE,
        #             headers="keys",
        #             showindex=False,
        #         )
        #     )

        if not args.only_originals and not args.only_duplicates:
            print()
