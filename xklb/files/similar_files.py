#!/usr/bin/python3

import argparse
from pathlib import Path

import humanize
from xklb.text import cluster_sort
from xklb.utils import arggroups

parser = argparse.ArgumentParser()
parser.add_argument('--small', action='store_true')
parser.add_argument('--size', action='store_true')
parser.add_argument('--only-duplicates', action='store_true')
parser.add_argument('--only-originals', action='store_true')
parser.add_argument('--n-clusters', '--clusters', type=int)
parser.add_argument('--dupes', type=float, default=2.5)
arggroups.debug(parser)
arggroups.paths_or_stdin(parser)
args = parser.parse_args()

paths = [str(f) for torrent_folder in args.paths for f in Path(torrent_folder).rglob('*')]

groups = cluster_sort.cluster_paths(paths, n_clusters=args.n_clusters or int(len(paths) / args.dupes))
groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_prefix"])))

if not args.only_originals and not args.only_duplicates:
    print("Duplicate groups:")

for group in groups:
    t = [(path, Path(path).stat().st_size) for path in group['grouped_paths']]
    t = sorted(t, key=lambda x: x[1], reverse=not args.small)

    if args.only_originals:
        t = t[:1]
    if args.only_duplicates:
        t = t[1:]

    for path, size in t:
        if args.size:
            print(path, '# ', humanize.naturalsize(size, binary=True))
        else:
            print(path)

    if not args.only_originals and not args.only_duplicates:
        print()
