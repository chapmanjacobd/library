import argparse, difflib, json, os.path, sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from xklb import usage
from xklb.scripts import mcda
from xklb.utils import consts, file_utils, iterables, nums, objects, printing, strings
from xklb.utils.consts import DBType
from xklb.utils.log_utils import Timer, log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library cluster-sort", usage=usage.cluster_sort)

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
        "-I",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help="Read image data",
    )
    profile.add_argument(
        "--audio",
        "-A",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Read audio data",
    )
    profile.add_argument(
        "--video",
        "-V",
        action="store_const",
        dest="profile",
        const=DBType.video,
        help="Read video data",
    )
    profile.add_argument(
        "--text",
        "-T",
        action="store_const",
        dest="profile",
        const=DBType.text,
        help="Read text data",
    )
    parser.set_defaults(profile="lines")

    parser.add_argument("--clusters", "--n-clusters", "-c", type=int, help="Number of KMeans clusters")
    parser.add_argument("--near-duplicates", "--similar-only", action="store_true", help="Re-group by difflib ratio")
    parser.add_argument(
        "--unique-only", action="store_true", help="Include only 'unique' lines (not including originals or duplicates)"
    )
    parser.add_argument("--exclude-unique", "--no-unique", action="store_true", help="Exclude 'unique' lines")
    parser.add_argument("--print-groups", "--groups", "-g", action="store_true", help="Print groups")
    parser.add_argument("--move-groups", "-M", action="store_true", help="Move groups into subfolders")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("input_path", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    parser.add_argument("output_path", nargs="?")
    args = parser.parse_args()

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def cluster_paths(paths, n_clusters=None):
    if len(paths) < 2:
        return paths

    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    sentence_strings = (strings.path_to_sentence(s) for s in paths)

    try:
        vectorizer = TfidfVectorizer(min_df=2, strip_accents="unicode", stop_words="english")
        X = vectorizer.fit_transform(sentence_strings)
    except ValueError:
        try:
            vectorizer = TfidfVectorizer(strip_accents="unicode", stop_words="english")
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

    grouped_strings = {}
    for i, group_string in enumerate(paths):
        cluster_id = clusters[i]

        if cluster_id not in grouped_strings:
            grouped_strings[cluster_id] = []

        grouped_strings[cluster_id].append(group_string)

    result = []
    for _cluster_id, paths in grouped_strings.items():
        paths = sorted(paths)
        common_prefix = os.path.commonprefix(paths)

        suffix_words = []
        for path in paths:
            suffix = path[len(common_prefix) :]
            words = list(iterables.ordered_set(strings.path_to_sentence(suffix).split()))
            suffix_words.extend(words)

        word_counts = Counter(suffix_words)
        common_words = [w for w, c in word_counts.items() if c > int(len(paths) * 0.6) and len(w) > 1]

        # join but preserve order
        suffix = "*".join(s for s in iterables.ordered_set(suffix_words) if s in common_words)

        metadata = {
            "common_prefix": common_prefix.strip() + "*" + suffix,
            "grouped_paths": paths,
        }
        result.append(metadata)

    return result


def cluster_dicts(args, media):
    if len(media) < 2:
        return media
    media_keyed = {d["path"]: d for d in media}
    groups = cluster_paths([d["path"] for d in media], n_clusters=getattr(args, "clusters", None))
    groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_prefix"])))

    if getattr(args, "sort_by", None) is not None:
        if args.sort_by in ("duration", "duration desc"):
            sorted_paths = iterables.flatten(
                sorted(d["grouped_paths"], key=lambda p: media_keyed[p]["duration"], reverse=" desc" in args.sort)
                for d in groups
            )
        else:
            groups = [
                {
                    **group,
                    "size": sum(media_keyed[s].get("size", 0) for s in group["grouped_paths"]),
                    "median_size": nums.safe_median(media_keyed[s].get("size", 0) for s in group["grouped_paths"]),
                    "total": len(group["grouped_paths"]),
                    "exists": sum(not bool(media_keyed[s].get("time_deleted", 0)) for s in group["grouped_paths"]),
                    "deleted": sum(bool(media_keyed[s].get("time_deleted", 0)) for s in group["grouped_paths"]),
                    "played": sum(bool(media_keyed[s].get("time_last_played", 0)) for s in group["grouped_paths"]),
                }
                for group in groups
            ]
            groups = mcda.group_sort_by(args, groups)
            sorted_paths = iterables.flatten(
                s for d in groups for s in d["grouped_paths"] if media_keyed[s].get("time_deleted", 0) == 0
            )
    else:
        sorted_paths = iterables.flatten(
            s for d in groups for s in d["grouped_paths"] if media_keyed[s].get("time_deleted", 0) == 0
        )
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
        metadata = {
            "common_prefix": common_prefix,
            "grouped_paths": sorted(paths),
        }
        result.append(metadata)
    log.info("common_prefix %s", t.elapsed())

    return result


def filter_near_duplicates(groups: List[Dict]) -> List[Dict]:
    regrouped_data = []

    for group in groups:
        temp_groups: Dict[str, List[str]] = {}
        for curr in group["grouped_paths"]:
            curr = curr.strip()
            if not curr or curr in ["'", '"']:
                continue

            is_duplicate = False
            for prev in temp_groups.keys():
                if difflib.SequenceMatcher(None, curr, prev).ratio() > 0.73:
                    temp_groups[prev].append(curr)
                    is_duplicate = True
                    break
            if not is_duplicate:
                temp_groups[curr] = []

        sorted_temp_groups = sorted(temp_groups.items(), key=lambda t: len(t[1]))
        for new_group_idx, (path, similar_paths) in enumerate(sorted_temp_groups):
            new_group_name = group["common_prefix"] + f"#{new_group_idx}"
            regrouped_data.append({"common_prefix": new_group_name, "grouped_paths": [path] + similar_paths})

    return regrouped_data


def cluster_sort() -> None:
    args = parse_args()

    lines = args.input_path.readlines()
    args.input_path.close()

    if args.profile == "lines":
        groups = cluster_paths(lines, args.clusters)
    elif args.profile == "image":
        groups = cluster_images(lines, args.clusters)
    else:
        raise NotImplementedError
    groups = sorted(groups, key=lambda d: (len(d["grouped_paths"]), -len(d["common_prefix"])))

    if args.near_duplicates:
        groups = filter_near_duplicates(groups)

    if args.exclude_unique:
        groups = [d for d in groups if len(d["grouped_paths"]) > 1]
    elif args.unique_only:
        groups = [d for d in groups if len(d["grouped_paths"]) == 1]

    if args.print_groups:
        for group in groups:
            group["grouped_paths"] = [s.rstrip("\n") for s in group["grouped_paths"]]

        print(json.dumps(groups))
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
