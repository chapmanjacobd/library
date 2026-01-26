import os
from pathlib import Path

import pytest

from library.__main__ import library as lb
from library.utils import consts, path_utils
from library.utils.path_utils import gen_rel_path
from tests.conftest import read_relative_file_tree_dict

simple_file_tree = {
    "folder1": {"file1.txt": "1", "subfolder1": {"file2.txt": "2"}},
    "folder2": {"file3.txt": "3"},
    "file4.txt": "4",
}


def test_simple_file(temp_file_tree):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    src1_inodes = read_relative_file_tree_dict(src1)

    target = temp_file_tree({})
    lb(["rel-mv", src1, target])

    assert read_relative_file_tree_dict(target) == path_utils.build_nested_dir_dict(
        consts.TEMP_DIR, {Path(src1).name: src1_inodes}
    )


def test_two_simple_folders_root(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree)
    src1_inodes = read_relative_file_tree_dict(src1)
    src2_inodes = read_relative_file_tree_dict(src2)

    target = temp_file_tree({})
    lb(["rel-mv", src1, src2, target])

    assert read_relative_file_tree_dict(target) == path_utils.build_nested_dir_dict(
        consts.TEMP_DIR, {Path(src1).name: src1_inodes} | {Path(src2).name: src2_inodes}
    )


def test_two_simple_folders_commonpath(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree)
    src1_inodes = read_relative_file_tree_dict(src1)
    src2_inodes = read_relative_file_tree_dict(src2)

    target = temp_file_tree({})
    lb(["rel-mv", "--relative-to=::", src1, src2, target])

    assert read_relative_file_tree_dict(target) == {Path(src1).name: src1_inodes} | {Path(src2).name: src2_inodes}


def test_dupe_delete_same(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree({Path(src1).name: simple_file_tree})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["rel-mv", "--relative-to=::", "--file-over-file=delete-src-hash skip", src1, target])

    assert read_relative_file_tree_dict(target) == target_inodes
    assert read_relative_file_tree_dict(src1) == {"file4.txt": src1_inodes["file4.txt"]}


def test_dupe_skip(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree({Path(src1).name: simple_file_tree})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["rel-mv", "--relative-to=::", "--file-over-file=skip", src1, target])

    assert read_relative_file_tree_dict(target) == target_inodes
    assert read_relative_file_tree_dict(src1) == src1_inodes


def test_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree({Path(src1).name: simple_file_tree})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["rel-mv", "--relative-to=::", "--file-over-file=delete-dest", src1, target])

    assert read_relative_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}
    assert not Path(src1).exists()


def test_folder_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "5"}})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["rel-mv", "--relative-to=::", src1, target])

    assert read_relative_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}
    assert not Path(src1).exists()


def test_file_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": {"file1": "5"}})
    target = temp_file_tree({"file1": "5"})

    src1_inodes = read_relative_file_tree_dict(src1)
    target_inodes = read_relative_file_tree_dict(target)
    lb(["rel-mv", "--relative-to=::", src1, target])

    assert read_relative_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}
    assert not Path(src1).exists()


@pytest.fixture
def test_dirs(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir(exist_ok=True)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir(exist_ok=True)
    return source_dir, dest_dir


def test_gen_rel_path(test_dirs):
    source_dir, dest_dir = test_dirs
    source = source_dir / "file.txt"
    source.touch()

    result = gen_rel_path(source, dest_dir, "::")
    expected = os.path.join(dest_dir, "source", "file.txt")
    assert result == expected


def test_gen_rel_path_from_subdir(test_dirs):
    source_dir, dest_dir = test_dirs
    source = source_dir / "subdir" / "file.txt"
    source.parent.mkdir(exist_ok=True)
    source.touch()

    result = gen_rel_path(source, dest_dir, "::")
    expected = os.path.join(dest_dir, "source", "subdir", "file.txt")
    assert result == expected


def test_gen_rel_path_relative(test_dirs):
    source_dir, dest_dir = test_dirs
    relative_to = source_dir
    relative_to.mkdir(exist_ok=True)
    source = source_dir / "file.txt"
    source.touch()

    result = gen_rel_path(source, dest_dir, relative_to=relative_to)
    expected = os.path.join(dest_dir, "file.txt")
    assert result == expected


def test_gen_rel_path_relative_deep(test_dirs):
    source_dir, dest_dir = test_dirs
    relative_to = source_dir / "t1"
    relative_to.mkdir(exist_ok=True, parents=True)
    source = source_dir / "t1" / "t2" / "t3" / "file.txt"
    source.mkdir(exist_ok=True, parents=True)
    source.touch()

    result = gen_rel_path(source, dest_dir, relative_to=relative_to)
    expected = os.path.join(dest_dir, "t2", "t3", "file.txt")
    assert result == expected
