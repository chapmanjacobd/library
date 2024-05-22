#!/usr/bin/env python3

# Copyright (c) 2016, Antonio SJ Musumeci <trapexit@spawn.link>
# Copyright (c) 2024, Jacob Chapman

# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.

# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

import argparse, os

import xattr

from xklb.utils import arggroups, argparse_utils, consts, processes


def parse_args():
    parser = argparse.ArgumentParser(description="Copy files with reflink and handle mergerfs mounts.")
    parser.add_argument("--simulate", "--dry-run", action="store_true", help="Dry run")
    parser.add_argument("--rel-mv", action="store_true", help="Use relative path")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    parser.add_argument("sources", nargs="+", action=argparse_utils.ArgparseArgsOrStdin, help="Source paths to copy")
    parser.add_argument("destination", help="Destination directory")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def get_mergerfs_mounts():
    mounts = []
    with open("/proc/self/mountinfo", "r") as f:
        for line in f:
            values = line.split()
            mountroot, mountpoint = values[3:5]
            separator = values.index("-", 6)
            fstype = values[separator + 1]
            if fstype == "fuse.mergerfs" and mountroot == "/":
                mounts.append(mountpoint.encode().decode("unicode_escape"))
    return mounts


def get_srcmounts(mergerfs_mount):
    ctrlfile = os.path.join(mergerfs_mount, ".mergerfs")
    return xattr.getxattr(ctrlfile, "user.mergerfs.srcmounts").decode().split(":")


def get_destination_mount(destination):
    mergerfs_mounts = get_mergerfs_mounts()

    lcp = ""
    for mergerfs_mount in mergerfs_mounts:
        common_path = os.path.commonpath([mergerfs_mount, destination])
        if len(common_path) > len(lcp):
            lcp = common_path
    return lcp


def mergerfs_cp():
    args = parse_args()

    args.sources = [os.path.realpath(s) for s in args.sources]
    args.destination = os.path.realpath(args.destination)

    mergerfs_mount = get_destination_mount(args.destination)
    srcmounts = get_srcmounts(mergerfs_mount)

    for source in args.sources:
        found_file = False
        for srcmount in srcmounts:
            relative_to_mount = os.path.relpath(source, mergerfs_mount)
            original_path = os.path.join(srcmount, relative_to_mount)
            if os.path.exists(original_path):
                found_file = True

                dest_path = args.destination
                if args.rel_mv:
                    dest_path = os.path.join(args.destination, relative_to_mount)

                cmd_args = ["cp", "-r"]
                if args.replace is None:
                    cmd_args.append("--interactive")
                elif args.replace is False:
                    cmd_args.append("--no-clobber")

                if not consts.PYTEST_RUNNING:
                    cmd_args.append("--reflink=always")
                cmd_args += [original_path, dest_path]

                if args.simulate:
                    print(*cmd_args)
                else:
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    processes.cmd(*cmd_args)

        if not found_file:
            print(f"Could not find srcmount of {source}")
            continue


if __name__ == "__main__":
    mergerfs_cp()
