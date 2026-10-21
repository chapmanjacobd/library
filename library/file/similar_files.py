import os
from itertools import combinations

from library import usage
from library.folder.similar_folders import cluster_folders, map_and_name
from library.utils import arggroups, argparse_utils, file_utils, filter_engine, nums, printing, shell_utils, strings
from library.utils.log_utils import log

MIN_CONTENT_GROUP_SIZE = 2


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.similar_files)
    arggroups.text_filtering(parser)
    arggroups.cluster_sort(parser)
    arggroups.files(parser, no_db=True)

    parser.add_argument("--small", "--reverse", action="store_true")
    parser.add_argument("--only-duplicates", action="store_true")
    parser.add_argument("--only-originals", action="store_true")

    parser.add_argument("--full-path", action="store_true", help="Cluster using full path instead of only file name")
    parser.add_argument("--estimated-duplicates", "--dupes", type=float)

    parser.add_argument("--durations-delta", "--duration-delta", type=float, default=10.0)
    parser.add_argument("--sizes-delta", "--size-delta", type=float, default=10.0)
    parser.add_argument(
        "--filter-content",
        "--content-similarity",
        "--content",
        action="store_true",
        help="Cluster files using deterministic sampled-content similarity",
    )
    parser.add_argument(
        "--content-threshold",
        "--similarity-threshold",
        type=float,
        default=0.7,
        help="Minimum sampled-content Jaccard similarity (default: 0.7)",
    )
    parser.add_argument(
        "--content-chunk-size",
        "--sample-chunk-size",
        type=int,
        default=10,
        help="Bytes in each sampled content chunk (default: 10)",
    )
    parser.add_argument(
        "--content-samples",
        "--sample-count",
        type=int,
        default=100,
        help="Number of deterministic content samples per file (default: 100)",
    )

    similar_parser = parser.add_argument_group("Similar Files")
    arggroups.similar_files(similar_parser)

    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()

    if not args.filter_names and not args.filter_sizes and not args.filter_durations and not args.filter_content:
        parser.error(
            "specify at least one filter mode: --filter-names, --filter-sizes, --filter-durations, or --filter-content"
        )
    if not 0 <= args.content_threshold <= 1:
        parser.error("--content-threshold must be between zero and one")
    if args.content_chunk_size < 1:
        parser.error("--content-chunk-size must be greater than zero")
    if args.content_samples < 1:
        parser.error("--content-samples must be greater than zero")

    arggroups.args_post(args, parser)
    arggroups.files_post(args)
    arggroups.similar_files_post(args)

    return args


def is_same_size_group(args, m0, m):
    bools = []

    if args.filter_sizes:
        size_diff = nums.percentage_difference(m0["size"], m["size"])
        bools.append(size_diff < args.sizes_delta)

    if args.filter_durations and m.get("duration"):
        duration_diff = nums.percentage_difference(m0["duration"], m["duration"])
        bools.append(duration_diff < args.durations_delta)

    return all(bools)


def cluster_by_size(args, media):
    group_id = 0
    temp_groups = []
    media_groups = []
    for m in media:
        grouped = False
        for i, group in enumerate(temp_groups):
            m0 = group[0]
            if is_same_size_group(args, m0, m):
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


def sample_positions(file_size: int, chunk_size: int, sample_count: int) -> list[int]:
    if file_size < 0:
        raise ValueError("file_size must not be negative")
    if chunk_size < 1:
        raise ValueError("chunk_size must be greater than zero")
    if sample_count < 1:
        raise ValueError("sample_count must be greater than zero")
    if file_size <= chunk_size:
        return [0]

    max_start = file_size - chunk_size
    count = min(sample_count, max_start + 1)
    if count == 1:
        return [0]
    return [(index * max_start) // (count - 1) for index in range(count)]


def sample_content(path, *, chunk_size=10, sample_count=100) -> set[bytes]:
    path = os.fspath(path)
    file_size = os.path.getsize(path)
    if file_size == 0:
        return {b""}

    samples = set()
    with open(path, "rb") as file_object:
        for position in sample_positions(file_size, chunk_size, sample_count):
            file_object.seek(position)
            samples.add(file_object.read(chunk_size))
    return samples


def hash_file(file_path, chunk_size=10, num_chunks=100) -> set[bytes]:
    return sample_content(file_path, chunk_size=chunk_size, sample_count=num_chunks)


def jaccard_similarity(samples_a: set[bytes], samples_b: set[bytes]) -> float:
    union = len(samples_a | samples_b)
    return len(samples_a & samples_b) / union if union else 0


def content_similarity(path_a, path_b, *, chunk_size=10, sample_count=100) -> float:
    samples_a = sample_content(path_a, chunk_size=chunk_size, sample_count=sample_count)
    samples_b = sample_content(path_b, chunk_size=chunk_size, sample_count=sample_count)
    return jaccard_similarity(samples_a, samples_b)


def find_similar_files(file_hashes, threshold=0.7):
    paths = sorted(file_hashes)
    similar_files = []
    for left, right in _content_candidate_pairs(file_hashes, threshold):
        file_a, file_b = paths[left], paths[right]
        similarity = jaccard_similarity(file_hashes[file_a], file_hashes[file_b])
        if similarity >= threshold:
            similar_files.append((similarity, file_a, file_b))
    return sorted(similar_files, key=lambda result: (result[0], result[1], result[2]))


def _content_candidate_pairs(file_hashes, threshold: float):
    paths = sorted(file_hashes)
    if threshold <= 0:
        yield from combinations(range(len(paths)), 2)
        return

    sample_index: dict[bytes, list[int]] = {}
    for index, path in enumerate(paths):
        for sample in file_hashes[path]:
            sample_index.setdefault(sample, []).append(index)

    candidates = set()
    for indexes in sample_index.values():
        candidates.update((left, right) for left, right in combinations(indexes, 2))
    yield from sorted(candidates)


def cluster_by_content(args, media):
    samples = {
        d["path"]: sample_content(
            d["path"],
            chunk_size=args.content_chunk_size,
            sample_count=args.content_samples,
        )
        for d in media
    }
    ordered_media = sorted(enumerate(media), key=lambda item: item[1]["path"])
    indexed_samples = {item["path"]: samples[item["path"]] for _, item in ordered_media}
    parent = list(range(len(media)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in _content_candidate_pairs(indexed_samples, args.content_threshold):
        similarity = jaccard_similarity(
            samples[ordered_media[left][1]["path"]],
            samples[ordered_media[right][1]["path"]],
        )
        if similarity >= args.content_threshold:
            union(ordered_media[left][0], ordered_media[right][0])

    roots = {}
    clusters = []
    for index in range(len(media)):
        root = find(index)
        if root not in roots:
            roots[root] = len(roots)
        clusters.append(roots[root])
    return clusters


def filter_group_by_size(args, group):
    media = group["grouped_paths"]

    m0 = media[0]
    output = [m for m in media[1:] if is_same_size_group(args, m0, m)]

    if output:
        group["grouped_paths"] = [m0, *output]
        return group
    return None


def filter_groups_by_size(args, groups):
    groups = [filter_group_by_size(args, group) for group in groups]
    groups = [group for group in groups if group]
    return groups


def filter_groups_by_content(args, groups):
    filtered_groups = []
    for group in groups:
        media = group["grouped_paths"]
        if len(media) < MIN_CONTENT_GROUP_SIZE:
            continue
        clusters = cluster_by_content(args, media)
        content_groups = map_and_name(media, clusters)
        filtered_groups.extend(group for group in content_groups if len(group["grouped_paths"]) > 1)
    return filtered_groups


def similar_files():  # noqa: PLR0912
    args = parse_args()
    media = list(shell_utils.gen_d(args))
    media = filter_engine.filter_items_by_criteria(args, media)

    groups: list[dict] = []
    if args.filter_sizes or args.filter_durations:
        media = filter_engine.filter_items_by_criteria(args, media)
        media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]

        clusters = cluster_by_size(args, media)
        groups = map_and_name(media, clusters)
        log.info("file size/duration clustering sorted %s files into %s groups", len(media), len(groups))
        single_file_groups = [d for d in groups if len(d["grouped_paths"]) == 1]
        groups = [d for d in groups if len(d["grouped_paths"]) > 1]
        log.info("Filtered out %s single-file groups", len(single_file_groups))
        log.debug(single_file_groups)

        if args.filter_names:
            media = [d for group in groups for d in group["grouped_paths"]]

    if args.filter_names:
        groups = cluster_folders(args, media)
        groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_path"])))
        log.info("Name clustering sorted %s files into %s groups", len(media), len(groups))

        if args.filter_sizes or args.filter_durations:
            prev_count = len(groups)
            groups = filter_groups_by_size(args, groups)  # effectively a second pass
            log.info("(2nd pass) group size/duration filtering removed %s groups", prev_count - len(groups))

    if args.filter_content:
        if groups:
            groups = filter_groups_by_content(args, groups)
        else:
            media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]
            clusters = cluster_by_content(args, media)
            groups = [group for group in map_and_name(media, clusters) if len(group["grouped_paths"]) > 1]
        log.info("content clustering sorted %s files into %s groups", len(media), len(groups))

    if not args.only_originals and not args.only_duplicates:
        print("Duplicate groups:")

    for group in groups:
        media = group["grouped_paths"]
        media = sorted(media, key=lambda d: d["size"], reverse=not args.small)

        if args.only_originals:
            media = media[:1]
        if args.only_duplicates:
            media = media[1:]

        if "f" in arggroups.get_compact_print_args(args):
            for d in media:
                printing.pipe_print(d["path"])
        else:
            printing.table(
                [
                    {
                        f"group {group['common_path']}": d["path"],
                        "size": strings.file_size(d["size"]),
                        "duration": strings.duration(d.get("duration")),
                    }
                    for d in media
                ]
            )

        if not args.only_originals and not args.only_duplicates:
            print()

    if not args.only_originals and not args.only_duplicates:
        print(len(groups), "groups found")
