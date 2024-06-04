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


@pytest.mark.parametrize("mode", ["move", "copy"])
@pytest.mark.parametrize("src", ["folder", "folder_bsd", "file", "not_exist"])
@pytest.mark.parametrize("dest", ["not_exist", "folder_merge", "clobber_file", "clobber_folder"])
@pytest.mark.parametrize("clobber", ["interactive", "no_replace", "replace"])
def test_copy(mode, src, dest, clobber, temp_file_tree):
    if src == "not_exist":
        src1 = temp_file_tree({})
    elif src == "file":
        src1 = temp_file_tree({"file4.txt": "5"}) + os.sep + "file4.txt"
    else:
        src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
        if src != "folder_bsd":
            src1 = src1 + os.sep

    if dest == "not_exist":
        target = temp_file_tree({})
    else:
        target = temp_file_tree(simple_file_tree)
        if dest == "clobber_file":
            target = os.path.join(target, "file4.txt")
        elif dest == "clobber_folder":
            target = os.path.join(target, "folder1", "file4.txt")
            # target = os.path.join(target, 'folder1', 'file4.txt', '')  # TODO: check if any different

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)

    cmd = ["merge-cp" if mode == "copy" else "merge-mv"]
    cmd += [src1, target]
    if clobber == "replace":
        cmd += ["--replace"]
    elif clobber == "no_replace":
        cmd += ["--no-replace"]

    if (
        clobber == "interactive"
        and src != "not_exist"
        and dest != "not_exist"
        and (src, dest) not in [("folder_bsd", "folder_merge")]
    ):
        with pytest.raises(devices.InteractivePrompt):
            lb(cmd)
        return
    else:
        lb(cmd)

    if mode == "copy":
        assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    else:
        assert not Path(src1).exists()

    if src == "not_exist":
        result = target_inodes
    elif src == "folder" and dest == "folder_merge":
        result = target_inodes | src1_inodes
    elif src == "folder_bsd" and dest == "not_exist":
        result = {Path(src1).name: src1_inodes}
    elif src == "folder_bsd" and dest == "folder_merge":
        result = target_inodes | {Path(src1).name: src1_inodes}
    elif dest in ("not_exist",):
        result = src1_inodes
    else:
        result = None

    assert generate_file_tree_dict(target, inodes=False) == result


def test_copy_simple_file(temp_file_tree):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    src1_inodes = generate_file_tree_dict(src1, inodes=False)

    target = temp_file_tree({})
    lb(["merge-cp", src1, target])

    assert generate_file_tree_dict(target, inodes=False) == {Path(src1).name: src1_inodes}


def test_copy_simple_tree(temp_file_tree):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    src1_inodes = generate_file_tree_dict(src1, inodes=False)

    target = temp_file_tree({})
    lb(["merge-cp", src1 + os.sep, target])

    assert generate_file_tree_dict(target, inodes=False) == src1_inodes


def test_copy_two_simple_folders(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree)
    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    src2_inodes = generate_file_tree_dict(src2, inodes=False)

    target = temp_file_tree({})
    lb(["merge-cp", src1, src2, target])

    assert generate_file_tree_dict(target, inodes=False) == {Path(src1).name: src1_inodes} | {
        Path(src2).name: src2_inodes
    }


def test_copy_dupe_no_replace(temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["merge-cp", "--no-replace", os.path.join(src1, "file4.txt"), target])
    lb(["merge-cp", "--no-replace", src1 + os.sep, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes


def test_copy_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["merge-cp", "--replace", src1, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | {Path(src1).name: src1_inodes}


def test_copy_dupe_replace_tree(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["merge-cp", "--replace", src1 + os.sep, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | src1_inodes


def test_copy_folder_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "4"}})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["merge-cp", "--replace", src1 + os.sep, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == {"file1": src1_inodes}


def test_copy_file_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": {"file1": "5"}})
    target = temp_file_tree({"file1": "5"})
    with pytest.raises(FileExistsError):
        lb(["merge-cp", "--replace", src1 + os.sep, target])


def test_move_simple_file(temp_file_tree):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    src1_inodes = generate_file_tree_dict(src1)

    target = temp_file_tree({})
    lb(["merge-mv", src1, target])

    assert generate_file_tree_dict(target) == {Path(src1).name: src1_inodes}


def test_move_two_simple_folders(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree)
    src1_inodes = generate_file_tree_dict(src1)
    src2_inodes = generate_file_tree_dict(src2)

    target = temp_file_tree({})
    lb(["merge-mv", src1, src2, target])

    assert generate_file_tree_dict(target) == {Path(src1).name: src1_inodes} | {Path(src2).name: src2_inodes}


def test_move_dupe_no_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree({Path(src1).name: simple_file_tree})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["merge-mv", "--no-replace", src1, target])

    assert generate_file_tree_dict(src1) == src1_inodes
    assert generate_file_tree_dict(target) == target_inodes


def test_move_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree({Path(src1).name: simple_file_tree})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["merge-mv", "--replace", src1, target])

    assert not Path(src1).exists()
    assert generate_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}


def test_move_folder_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "5"}})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["merge-mv", src1, target])

    assert not Path(src1).exists()
    assert generate_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}


def test_move_file_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": {"file1": "5"}})
    target = temp_file_tree({"file1": "5"})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["merge-mv", src1, target])

    assert not Path(src1).exists()
    assert generate_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}


# TODO: test same-file same-folder
