from pathlib import Path

from tests.conftest import generate_file_tree_dict
from xklb.lb import library as lb

simple_file_tree = {
    "folder1": {"file1.txt": "1", "subfolder1": {"file2.txt": "2"}},
    "folder2": {"file3.txt": "3"},
    "file4.txt": "4",
}


def test_simple_file(temp_file_tree):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    target = temp_file_tree({})
    lb(["merge-folders", "--replace", src1, target])

    assert generate_file_tree_dict(target) == file_tree


def test_simple_folder(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    target = temp_file_tree({})
    lb(["merge-folders", "--no-replace", src1, target])

    assert generate_file_tree_dict(target) == simple_file_tree


def test_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)
    lb(["merge-folders", "--replace", src1, target])

    assert not Path(src1).exists()
    assert generate_file_tree_dict(target) == simple_file_tree | {"file4.txt": "5"}


def test_dupe_skip(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)
    lb(["merge-folders", "--no-replace", src1, target])

    assert Path(src1).exists()
    assert generate_file_tree_dict(src1) == simple_file_tree | {"file4.txt": "5"}
    assert generate_file_tree_dict(target) == simple_file_tree


def test_folder_conflict_replace(temp_file_tree):
    src1_tree = {"file1": "5"}
    target_tree = {"file1": {"file1": "5"}}
    src1 = temp_file_tree(src1_tree)
    target = temp_file_tree(target_tree)
    lb(["merge-folders", "--replace", src1, target])

    assert Path(src1).exists()
    assert generate_file_tree_dict(src1) == src1_tree
    assert generate_file_tree_dict(target) == target_tree


def test_file_conflict_replace(temp_file_tree):
    src1_tree = {"file1": {"file1": "5"}}
    target_tree = {"file1": "5"}
    src1 = temp_file_tree(src1_tree)
    target = temp_file_tree(target_tree)
    lb(["merge-folders", "--replace", src1, target])

    assert Path(src1).exists()
    assert generate_file_tree_dict(src1) == src1_tree
    assert generate_file_tree_dict(target) == target_tree


def test_folder_conflict_skip(temp_file_tree):
    src1_tree = {"file1": "5"}
    target_tree = {"file1": {"file1": "5"}}
    src1 = temp_file_tree(src1_tree)
    target = temp_file_tree(target_tree)
    lb(["merge-folders", "--no-replace", src1, target])

    assert Path(src1).exists()
    assert generate_file_tree_dict(src1) == src1_tree
    assert generate_file_tree_dict(target) == target_tree


def test_file_conflict_skip(temp_file_tree):
    src1_tree = {"file1": {"file1": "5"}}
    target_tree = {"file1": "5"}
    src1 = temp_file_tree(src1_tree)
    target = temp_file_tree(target_tree)
    lb(["merge-folders", "--no-replace", src1, target])

    assert Path(src1).exists()
    assert generate_file_tree_dict(src1) == src1_tree
    assert generate_file_tree_dict(target) == target_tree
