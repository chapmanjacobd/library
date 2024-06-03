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

import os

from xklb import usage
from xklb.utils import arggroups, argparse_utils, consts, file_utils, path_utils, processes


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.mergerfs_cp)
    parser.add_argument("--simulate", "--dry-run", action="store_true", help="Dry run")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser, destination=True)
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
    import xattr

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


def mcp_file(args, source, destination):
    found_file = False
    for srcmount in args.srcmounts:
        relative_to_mount = os.path.relpath(source, args.mergerfs_mount)
        original_path = os.path.join(srcmount, relative_to_mount)
        if os.path.exists(original_path):
            found_file = True
            destination = os.path.join(srcmount, os.path.relpath(destination, args.mergerfs_mount))

            src_dest = [original_path, destination]
            if args.simulate:
                print(*args.cp_args, *src_dest)
            else:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                processes.cmd(*args.cp_args, *src_dest, strict=False, quiet=False, error_verbosity=2)

    if not found_file:
        print(f"Could not find srcmount of {source}")


def cp_args(args):
    cmd_args = ["cp"]
    if args.replace is None:
        cmd_args.append("--interactive")
    elif args.replace is False:
        cmd_args.append("--no-clobber")

    if not consts.PYTEST_RUNNING:
        cmd_args.append("--reflink=always")
    return cmd_args


def mergerfs_cp():
    args = parse_args()

    args.cp_args = cp_args(args)
    args.destination = os.path.realpath(args.destination)
    args.mergerfs_mount = get_destination_mount(args.destination)
    if args.mergerfs_mount == "":
        processes.exit_error("Could not detect any mergerfs mounts")
    args.srcmounts = get_srcmounts(args.mergerfs_mount)

    sources = (
        os.path.realpath(s) + (os.sep if s.endswith(os.sep) else "") for s in args.paths
    )  # preserve trailing slash
    for source in sources:
        if os.path.isdir(source):
            for p in file_utils.rglob(source, args.ext or None)[0]:
                cp_dest = args.destination
                if not source.endswith(os.sep):  # use BSD behavior
                    cp_dest = os.path.join(cp_dest, os.path.basename(source))
                cp_dest = os.path.join(cp_dest, os.path.relpath(p, source))

                mcp_file(args, p, cp_dest)
        else:
            cp_dest = args.destination
            if path_utils.is_folder_dest(source, cp_dest):
                cp_dest = os.path.join(args.destination, os.path.basename(source))

            mcp_file(args, source, cp_dest)


if __name__ == "__main__":
    mergerfs_cp()
