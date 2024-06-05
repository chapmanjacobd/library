import os
from pathlib import Path

import pytest

from tests.conftest import generate_file_tree_dict
from xklb.lb import library as lb
from xklb.utils import devices

simple_file_tree = {
    "folder1": {"file1.txt": "1", "file4.txt": {"file2.txt": "2"}},
    "folder2": {".hidden": "3"},
    "file4.txt": "4",
}


@pytest.mark.parametrize("subcommand", ["merge-cp", "merge-mv"])
@pytest.mark.parametrize("src_type", ["folder", "folder_bsd", "file", "not_exist"])
@pytest.mark.parametrize("dest_type", ["not_exist", "folder_merge", "clobber_file", "clobber_folder"])
@pytest.mark.parametrize("clobber", ["interactive", "no_replace", "replace"])
def test_merge(subcommand, src_type, dest_type, clobber, temp_file_tree):
    if dest_type == "clobber_folder" and src_type != "file":
        return  # not useful to test

    if src_type == "not_exist":
        src1 = temp_file_tree({})
    elif src_type == "file":
        src1 = temp_file_tree({"file4.txt": "5"}) + os.sep + "file4.txt"
    else:  # folder, folder_bsd
        src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
        if src_type != "folder_bsd":
            src1 = src1 + os.sep

    if dest_type == "not_exist":
        dest = temp_file_tree({})
    else:
        dest = temp_file_tree(simple_file_tree)
        if dest_type == "clobber_file":
            dest = os.path.join(dest, "file4.txt")
        elif dest_type == "clobber_folder":
            dest = os.path.join(dest, "folder1")

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_inodes = generate_file_tree_dict(dest, inodes=False)

    cmd = [subcommand]
    cmd += [src1, dest]
    if clobber == "replace":
        cmd += ["--replace"]
    elif clobber == "no_replace":
        cmd += ["--no-replace"]

    if (
        clobber == "interactive"
        and src_type != "not_exist"
        and dest_type != "not_exist"
        and dest_type != "clobber_folder"
        and (src_type, dest_type) not in [("folder_bsd", "folder_merge")]
    ):
        with pytest.raises(devices.InteractivePrompt):
            lb(cmd)
        return
    else:
        lb(cmd)

    if subcommand == "merge-cp":
        assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    elif clobber != "no_replace":
        assert not Path(src1).exists()

    target_inodes = generate_file_tree_dict(dest, inodes=False)
    if src_type == "not_exist":
        assert target_inodes == dest_inodes
    elif src_type == "folder_bsd" and dest_type == "not_exist":
        assert target_inodes == {Path(src1).name: src1_inodes}
    elif dest_type in ("not_exist",):
        assert target_inodes == src1_inodes

    elif src_type == "folder_bsd" and dest_type == "folder_merge":
        assert target_inodes == dest_inodes | {Path(src1).name: src1_inodes}

    elif dest_type == "folder_merge" and clobber == "replace":
        assert target_inodes == dest_inodes | src1_inodes
    elif dest_type == "folder_merge":
        assert target_inodes == dest_inodes

    elif dest_type == "clobber_folder":
        dest_inodes["file4.txt"] = dest_inodes["file4.txt"] | src1_inodes  # type: ignore
        assert target_inodes == dest_inodes

    elif src_type == "folder_bsd" and dest_type == "clobber_file" and clobber == "replace":
        assert target_inodes == {Path(src1).name: src1_inodes}
    elif dest_type == "clobber_file" and clobber == "replace":
        assert target_inodes == src1_inodes
    elif dest_type == "clobber_file":
        assert target_inodes == dest_inodes

    else:
        raise NotImplementedError


@pytest.mark.parametrize("subcommand", ["merge-mv", "merge-cp"])
def test_merge_two_simple_folders(subcommand, temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    src1_inodes = generate_file_tree_dict(src1, inodes=subcommand == "merge-mv")
    src2_inodes = generate_file_tree_dict(src2, inodes=subcommand == "merge-mv")

    target = temp_file_tree({})
    lb([subcommand, src1, src2, target])

    if subcommand == "merge-cp":
        assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
        assert generate_file_tree_dict(src2, inodes=False) == src2_inodes
    else:
        assert not os.path.exists(src1)
        assert not os.path.exists(src2)

    expected = {Path(src1).name: src1_inodes} | {Path(src2).name: src2_inodes}
    assert generate_file_tree_dict(target, inodes=subcommand == "merge-mv") == expected


@pytest.mark.parametrize("subcommand", ["merge-mv", "merge-cp"])
def test_same_file(subcommand, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "4"}) + os.sep + "file4.txt"
    src1_inodes = generate_file_tree_dict(src1)

    lb([subcommand, src1, src1])
    assert generate_file_tree_dict(src1) == src1_inodes


@pytest.mark.parametrize("subcommand", ["merge-mv", "merge-cp"])
def test_same_folder(subcommand, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "4"})
    src1_inodes = generate_file_tree_dict(src1)

    lb([subcommand, src1 + os.sep, src1 + os.sep])
    assert generate_file_tree_dict(src1) == src1_inodes
