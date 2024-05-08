import argparse, difflib, json, sys
from pathlib import Path

from xklb import usage
from xklb.tablefiles import eda, mcda
from xklb.utils import (
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    file_utils,
    iterables,
    nums,
    objects,
    path_utils,
    printing,
    strings,
)
from xklb.utils.consts import DBType
from xklb.utils.log_utils import Timer, log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library cluster-sort", usage=usage.cluster_sort)

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--lines",
        action="store_const",
        dest="profile",
        const="lines",
        help="Cluster lines AS-IS",
    )
    profile.add_argument(
        "--image",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help="Read image data",
    )
    profile.add_argument(
        "--audio",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Read audio data",
    )
    profile.add_argument(
        "--video",
        action="store_const",
        dest="profile",
        const=DBType.video,
        help="Read video data",
    )
    profile.add_argument(
        "--text",
        action="store_const",
        dest="profile",
        const=DBType.text,
        help="Read text data",
    )
    parser.set_defaults(profile="lines")

    arggroups.cluster(parser)
    parser.set_defaults(cluster_sort=True)
    arggroups.debug(parser)

    parser.add_argument("input_path", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    parser.add_argument("output_path", nargs="?")
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    return args


def map_cluster_to_paths(paths, clusters):
    grouped_strings = {}
    for i, group_string in enumerate(paths):
        cluster_id = clusters[i]

        if cluster_id not in grouped_strings:
            grouped_strings[cluster_id] = []

        grouped_strings[cluster_id].append(group_string)
    return grouped_strings


def map_and_name(paths, clusters):
    grouped_strings = map_cluster_to_paths(paths, clusters)

    result = []
    for _cluster_id, paths in grouped_strings.items():
        paths = sorted(paths)
        metadata = {"common_path": path_utils.common_path(paths), "grouped_paths": paths}
        result.append(metadata)
    return result


def find_clusters(n_clusters, sentence_strings, stop_words=None):
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    if stop_words is None:
        from xklb.data import wordbank

        stop_words = wordbank.stop_words

    try:
        vectorizer = TfidfVectorizer(min_df=2, strip_accents="unicode", stop_words=stop_words)
        X = vectorizer.fit_transform(sentence_strings)
    except ValueError:
        try:
            vectorizer = TfidfVectorizer(strip_accents="unicode", stop_words=stop_words)
            X = vectorizer.fit_transform(sentence_strings)
        except ValueError:
            try:
                vectorizer = TfidfVectorizer()
                X = vectorizer.fit_transform(sentence_strings)
            except ValueError:
                vectorizer = TfidfVectorizer(analyzer="char_wb")
                X = vectorizer.fit_transform(sentence_strings)

    clusterizer = KMeans(n_clusters=n_clusters or int(X.shape[0] ** 0.5), random_state=0, n_init=10).fit(X)
    clusters = clusterizer.labels_
    return clusters


def cluster_paths(paths, n_clusters=None, stop_words=None):
    if len(paths) < 3:
        return paths

    sentence_strings = (strings.path_to_sentence(s) for s in paths)
    clusters = find_clusters(n_clusters, sentence_strings, stop_words=stop_words)
    result = map_and_name(paths, clusters)

    return result


def print_groups(groups):
    for group in groups:
        group["grouped_paths"] = [s.rstrip("\n") for s in group["grouped_paths"]]

    print(json.dumps(groups, indent=4))
    raise SystemExit(0)


def cluster_dicts(args, media):
    if len(media) < 3:
        return media

    n_clusters = getattr(args, "clusters", None)
    search_columns = {
        col
        for _table, table_config in db_utils.config.items()
        if "search_columns" in table_config
        for col in table_config["search_columns"]
    }

    media_keyed = {d["path"]: d for d in media}
    paths = [d["path"] for d in media]
    sentence_strings = (
        strings.path_to_sentence(" ".join(str(v) for k, v in d.items() if v and k in search_columns)) for d in media
    )

    clusters = find_clusters(n_clusters, sentence_strings, stop_words=getattr(args, "stop_words", None))

    if args.verbose >= consts.LOG_INFO:
        from pandas import DataFrame

        eda.print_info(objects.NoneSpace(end_row="inf"), DataFrame(clusters))

    groups = map_and_name(paths, clusters)
    groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_path"])))

    if getattr(args, "sort_groups_by", None):
        if args.sort_groups_by in ("duration", "duration desc"):
            sorted_paths = iterables.flatten(
                sorted(d["grouped_paths"], key=lambda p: media_keyed[p]["duration"], reverse=" desc" in args.sort)
                for d in groups
            )
        else:
            groups = [
                {
                    **group,
                    "size": sum(
                        media_keyed[s].get("size") or 0
                        for s in group["grouped_paths"]
                        if not bool(media_keyed[s].get("time_deleted"))
                    ),
                    "median_size": nums.safe_median(
                        media_keyed[s].get("size") or 0
                        for s in group["grouped_paths"]
                        if not bool(media_keyed[s].get("time_deleted"))
                    ),
                    "total": len(group["grouped_paths"]),
                    "exists": sum(not bool(media_keyed[s].get("time_deleted")) for s in group["grouped_paths"]),
                    "deleted": sum(bool(media_keyed[s].get("time_deleted")) for s in group["grouped_paths"]),
                    "deleted_size": sum(
                        media_keyed[s].get("size") or 0
                        for s in group["grouped_paths"]
                        if bool(media_keyed[s].get("time_deleted"))
                    ),
                    "played": sum(bool(media_keyed[s].get("time_last_played")) for s in group["grouped_paths"]),
                }
                for group in groups
            ]
            groups = mcda.group_sort_by(args, groups)
            sorted_paths = iterables.flatten(
                s for d in groups for s in d["grouped_paths"] if not bool(media_keyed[s].get("time_deleted"))
            )
    else:
        sorted_paths = iterables.flatten(
            s for d in groups for s in d["grouped_paths"] if not bool(media_keyed[s].get("time_deleted"))
        )

    if getattr(args, "print_groups", False):
        print_groups(groups)

    media = [media_keyed[p] for p in sorted_paths]
    return media


def cluster_images(paths, n_clusters=None):
    paths = [s.rstrip("\n") for s in paths]
    t = Timer()

    import os

    import numpy as np
    from annoy import AnnoyIndex
    from PIL import Image

    log.info("imports %s", t.elapsed())
    index_dir = "image_cluster_indexes"
    os.makedirs(index_dir, exist_ok=True)

    img_size = 100  # trade-off between accuracy and speed

    image_mode_groups = {}
    for path in paths:
        img = Image.open(path)
        img = img.resize((img_size, img_size), Image.Resampling.NEAREST)
        img_array = np.array(img).reshape(-1)  # convert to scalar for ANNoy
        mode = img.mode
        if mode not in image_mode_groups:
            image_mode_groups[mode] = []
        image_mode_groups[mode].append(img_array)
    log.info("image_mode_groups %s", t.elapsed())

    annoy_indexes = {}
    for mode, images in image_mode_groups.items():
        dimension = images[0].shape[0]

        annoy_index = AnnoyIndex(dimension, "angular")
        for i, vector in enumerate(images):
            annoy_index.add_item(i, vector)

        annoy_index.build(100)  # trade-off between accuracy and speed
        annoy_indexes[mode] = annoy_index
    log.info("annoy_index %s", t.elapsed())

    clusters = []
    for mode, images in image_mode_groups.items():
        annoy_index = annoy_indexes[mode]
        for i in range(len(images)):
            nearest_neighbors = annoy_index.get_nns_by_item(i, n_clusters or int(len(images) ** 0.6))
            clusters.extend([i] * len(nearest_neighbors))
    log.info("image_mode_groups %s", t.elapsed())

    grouped_strings = {}
    for i, group_string in enumerate(paths):
        cluster_id = clusters[i]

        if cluster_id not in grouped_strings:
            grouped_strings[cluster_id] = []

        grouped_strings[cluster_id].append(group_string + "\n")
    log.info("grouped_strings %s", t.elapsed())

    result = []
    for _cluster_id, paths in grouped_strings.items():
        common_prefix = os.path.commonprefix(paths)
        metadata = {"common_path": common_prefix, "grouped_paths": sorted(paths)}
        result.append(metadata)
    log.info("common_prefix %s", t.elapsed())

    return result


def filter_near_duplicates(groups: list[dict]) -> list[dict]:
    regrouped_data = []

    for group in groups:
        temp_groups: dict[str, list[str]] = {}
        for curr in group["grouped_paths"]:
            curr = curr.strip()
            if not curr or curr in ["'", '"']:
                continue

            is_duplicate = False
            for prev in temp_groups.keys():
                if difflib.SequenceMatcher(None, curr, prev).ratio() > consts.DEFAULT_DIFFLIB_RATIO:
                    temp_groups[prev].append(curr)
                    is_duplicate = True
                    break
            if not is_duplicate:
                temp_groups[curr] = []

        sorted_temp_groups = sorted(temp_groups.items(), key=lambda t: len(t[1]))
        for new_group_idx, (path, similar_paths) in enumerate(sorted_temp_groups):
            new_group_name = group["common_path"] + f"#{new_group_idx}"
            regrouped_data.append({"common_path": new_group_name, "grouped_paths": [path] + similar_paths})

    return regrouped_data


def cluster_sort() -> None:
    args = parse_args()

    lines = args.input_path.readlines()
    args.input_path.close()

    if args.profile == "lines":
        groups = cluster_paths(lines, args.clusters, args.stop_words)
    elif args.profile == "image":
        groups = cluster_images(lines, args.clusters)
    else:
        raise NotImplementedError
    groups = sorted(groups, key=lambda d: (len(d["grouped_paths"]), -len(d["common_path"])))

    if args.near_duplicates:
        groups = filter_near_duplicates(groups)

    if args.exclude_unique:
        groups = [d for d in groups if len(d["grouped_paths"]) > 1]
    elif args.unique_only:
        groups = [d for d in groups if len(d["grouped_paths"]) == 1]

    if getattr(args, "print_groups", False):
        print_groups(groups)
    elif args.move_groups:
        min_len = len(str(len(groups) + 1))

        if args.profile == "lines":
            if args.output_path:
                output_parent = Path(args.output_path).parent
                output_name = Path(args.output_path).name
            elif args.input_path.name == "<stdin>" or Path(args.input_path.name).parent == consts.TEMP_DIR:
                output_parent = Path.cwd()
                output_name = "stdin"
            else:
                output_parent = Path(args.input_path.name).parent
                output_name = Path(args.input_path.name).name

            for i, group in enumerate(groups, start=1):
                output_path = output_parent / (output_name + "_" + str(i).zfill(min_len))
                with open(output_path, "w") as output_fd:
                    output_fd.writelines(group["grouped_paths"])

        elif args.profile in ("image",):
            for i, group in enumerate(groups, start=1):
                paths = [s.rstrip("\n") for s in group["grouped_paths"]]
                file_utils.move_files([(p, str(Path(p).parent / str(i).zfill(min_len) / Path(p).name)) for p in paths])
    else:
        lines = iterables.flatten(d["grouped_paths"] for d in groups)
        if args.output_path:
            with open(args.output_path, "w") as output_fd:
                output_fd.writelines(lines)
        else:
            printing.pipe_lines(lines)


if __name__ == "__main__":
    cluster_sort()
