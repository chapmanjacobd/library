import os, subprocess, tempfile
from pathlib import Path

import pytest

from tests.conftest import generate_file_tree_dict
from xklb.lb import library as lb

simple_file_tree = {
    "folder1": {"file1.txt": "1", "subfolder1": {"file2.txt": "2"}},
    "folder2": {"file3.txt": "3"},
    "file4.txt": "4",
}


@pytest.fixture(autouse=True)
def mock_get_mergerfs_mounts(monkeypatch):
    from xklb.folders import mergerfs_cp

    temp_dir = tempfile.gettempdir()
    monkeypatch.setattr(mergerfs_cp, "get_mergerfs_mounts", lambda: [temp_dir])
    monkeypatch.setattr(mergerfs_cp, "get_srcmounts", lambda _: [temp_dir])


def test_simple_file(temp_file_tree):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    src1_inodes = generate_file_tree_dict(src1, inodes=False)

    target = temp_file_tree({})
    lb(["mergerfs-cp", src1, target])

    assert generate_file_tree_dict(target, inodes=False) == {Path(src1).name: src1_inodes}


def test_two_simple_folders(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree)
    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    src2_inodes = generate_file_tree_dict(src2, inodes=False)

    target = temp_file_tree({})
    lb(["mergerfs-cp", src1, src2, target])

    assert generate_file_tree_dict(target, inodes=False) == {Path(src1).name: src1_inodes} | {
        Path(src2).name: src2_inodes
    }


def test_dupe_no_replace(temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    with pytest.raises(subprocess.CalledProcessError):
        lb(["mergerfs-cp", "--no-replace", os.path.join(src1, "file4.txt"), target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes


def test_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["mergerfs-cp", "--replace", src1, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | {Path(src1).name: src1_inodes}


def test_folder_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "5"}})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["mergerfs-cp", src1, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | {Path(src1).name: src1_inodes}


def test_file_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": {"file1": "5"}})
    target = temp_file_tree({"file1": "5"})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["mergerfs-cp", src1, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | {Path(src1).name: src1_inodes}
