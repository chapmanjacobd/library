from pathlib import Path

from library.__main__ import library as lb
from tests.conftest import read_relative_file_tree_dict

simple_file_tree = {
    "folder1": {"file1.txt": "1", "subfolder1": {"file2.txt": "2"}},
    "folder2": {"file3.txt": "3"},
    "file4.txt": "4",
}


def test_simple_file(temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "4"})
    target = temp_file_tree({})

    src1_inodes = read_relative_file_tree_dict(src1)
    lb(["merge-folders", "--replace", src1, target])

    assert read_relative_file_tree_dict(target) == src1_inodes


def test_simple_folder(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    target = temp_file_tree({})

    src1_inodes = read_relative_file_tree_dict(src1)
    lb(["merge-folders", "--no-replace", src1, target])

    assert read_relative_file_tree_dict(target) == src1_inodes


def test_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["merge-folders", "--replace", src1, target])

    assert not Path(src1).exists()
    assert read_relative_file_tree_dict(target) == target_inodes | src1_inodes


def test_dupe_skip(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["merge-folders", "--no-replace", src1, target])

    assert Path(src1).exists()
    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(target) == target_inodes


def test_folder_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "5"}})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["merge-folders", "--replace", src1, target])

    assert Path(src1).exists()
    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(target) == target_inodes


def test_file_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": {"file1": "5"}})
    target = temp_file_tree({"file1": "5"})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["merge-folders", "--replace", src1, target])

    assert Path(src1).exists()
    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(target) == target_inodes


def test_folder_conflict_skip(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "5"}})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["merge-folders", "--no-replace", src1, target])

    assert Path(src1).exists()
    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(target) == target_inodes


def test_file_conflict_skip(temp_file_tree):
    src1 = temp_file_tree({"file1": {"file1": "5"}})
    target = temp_file_tree({"file1": "5"})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["merge-folders", "--no-replace", src1, target])

    assert Path(src1).exists()
    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(target) == target_inodes
