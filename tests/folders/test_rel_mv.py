from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import OSType

from tests.conftest import generate_file_tree_dict
from xklb.__main__ import library as lb
from xklb.folders.rel_mv import gen_rel_path, relative_from_path, shortest_relative_from_path

simple_file_tree = {
    "folder1": {"file1.txt": "1", "subfolder1": {"file2.txt": "2"}},
    "folder2": {"file3.txt": "3"},
    "file4.txt": "4",
}


def test_simple_file(temp_file_tree):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    src1_inodes = generate_file_tree_dict(src1)

    target = temp_file_tree({})
    lb(["rel-mv", src1, target])

    assert generate_file_tree_dict(target) == {Path(src1).name: src1_inodes}


def test_two_simple_folders(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree)
    src1_inodes = generate_file_tree_dict(src1)
    src2_inodes = generate_file_tree_dict(src2)

    target = temp_file_tree({})
    lb(["rel-mv", src1, src2, target])

    assert generate_file_tree_dict(target) == {Path(src1).name: src1_inodes} | {Path(src2).name: src2_inodes}


def test_dupe_no_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree({Path(src1).name: simple_file_tree})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["rel-mv", "--no-replace", src1, target])

    assert generate_file_tree_dict(src1) == {
        "folder1": {"subfolder1": {}},
        "folder2": {},
        "file4.txt": src1_inodes["file4.txt"],
    }
    assert generate_file_tree_dict(target) == target_inodes


def test_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree({Path(src1).name: simple_file_tree})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["rel-mv", "--replace", src1, target])

    assert generate_file_tree_dict(src1) == {"folder1": {"subfolder1": {}}, "folder2": {}}
    assert generate_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}


def test_folder_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "5"}})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["rel-mv", src1, target])

    assert not Path(src1).exists()
    assert generate_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}


def test_file_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": {"file1": "5"}})
    target = temp_file_tree({"file1": "5"})

    src1_inodes = generate_file_tree_dict(src1)
    target_inodes = generate_file_tree_dict(target)
    lb(["rel-mv", src1, target])

    assert not Path(src1).exists()
    assert generate_file_tree_dict(target) == target_inodes | {Path(src1).name: src1_inodes}


def test_relative_from_path(fs):
    fs.os = OSType.LINUX
    assert relative_from_path("/path/test/file.txt", "/path/") == Path("test/file.txt")
    assert relative_from_path("/path/test/file.txt", "path/") == Path("test/file.txt")
    assert relative_from_path("/path/test/file.txt", "/test/") == Path("path/test/file.txt")
    assert relative_from_path("/path/test/file.txt", "test/") == Path("path/test/file.txt")
    assert relative_from_path("/path/test/file.txt", "../") == Path("test/file.txt")
    assert relative_from_path("/path/test/file.txt", "../test") == Path("file.txt")
    assert relative_from_path("/path/test/file.txt", "../test/") == Path("file.txt")
    assert relative_from_path("/path/test/file.txt", "../../") == Path("file.txt")


def test_relative_from_path_windows(fs):
    fs.os = OSType.WINDOWS
    assert relative_from_path(r"C:\path\test\file.txt", "path\\") == Path("test\\file.txt")
    assert relative_from_path(r"C:\path\test\file.txt", "test\\") == Path("path\\test\\file.txt")
    assert relative_from_path(r"C:\path\test\file.txt", "..\\") == Path("test\\file.txt")
    assert relative_from_path(r"C:\path\test\file.txt", "..\\test") == Path("file.txt")
    assert relative_from_path(r"C:\path\test\file.txt", "..\\test\\") == Path("file.txt")
    assert relative_from_path(r"C:\path\test\file.txt", "..\\..\\") == Path("file.txt")


def test_shortest_relative_from_path(fs):
    fs.os = OSType.LINUX

    relative_from_list = ["/path/to", "/another/path", "/yet/another/path", "../test/"]

    assert shortest_relative_from_path("/path/test/file.txt", ["/path/", "../test/"]) == Path("file.txt")
    assert shortest_relative_from_path("/path/test/file.txt", ["/path/", "/test/"]) == Path("test/file.txt")
    assert shortest_relative_from_path("/path/to/some/file.txt", relative_from_list) == Path("some/file.txt")
    assert shortest_relative_from_path("/path/test/file.txt", relative_from_list) == Path("file.txt")
    assert shortest_relative_from_path("/path/test/file.txt", ["test/"]) == Path("path/test/file.txt")
    assert shortest_relative_from_path("/path/test/file.txt", ["/"]) == Path("path/test/file.txt")
    assert shortest_relative_from_path("/path/test/file.txt", ["/yet/wrong/"]) == Path("path/test/file.txt")


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

    result = gen_rel_path(source, dest_dir)
    expected = dest_dir / "source" / "file.txt"
    assert result == expected


def test_gen_rel_path_from_subdir(test_dirs):
    source_dir, dest_dir = test_dirs
    source = source_dir / "subdir" / "file.txt"
    source.parent.mkdir(exist_ok=True)
    source.touch()

    result = gen_rel_path(source, dest_dir)
    expected = dest_dir / "source" / "subdir" / "file.txt"
    assert result == expected


def test_gen_rel_path_relative(test_dirs):
    source_dir, dest_dir = test_dirs
    relative_from = source_dir
    relative_from.mkdir(exist_ok=True)
    source = source_dir / "file.txt"
    source.touch()

    result = gen_rel_path(source, dest_dir, relative_from=relative_from)
    expected = dest_dir / "file.txt"
    assert result == expected


def test_gen_rel_path_relative_deep(test_dirs):
    source_dir, dest_dir = test_dirs
    relative_from = source_dir / "t1"
    relative_from.mkdir(exist_ok=True, parents=True)
    source = source_dir / "t1" / "t2" / "t3" / "file.txt"
    source.mkdir(exist_ok=True, parents=True)
    source.touch()

    result = gen_rel_path(source, dest_dir, relative_from=relative_from)
    expected = dest_dir / "t2" / "t3" / "file.txt"
    assert result == expected
