
import pytest
from library.utils import path_utils


paths_abs = [
    "/a/file1.txt",
    "/a/file2.txt",
    "/a/b/file3.txt",
    "/a/c/file4.txt",
    "/d/file5.txt",
]
paths_rel = [
    "root/a/file1.txt",
    "root/a/b/file2.txt",
    "root/a/c/file3.txt",
    "root/d/file4.txt",
]
paths_remote = [
    "http://a.com/file1.txt",
    "http://a.com/file2.txt",
    "http://a.com/b/file3.txt",
    "http://a.com/c/file4.txt",
    "http://d.com/file5.txt",
]


@pytest.mark.parametrize(
    "paths,dir_path,expected",
    [
        (paths_abs, "/", {"/a", "/d"}),
        (paths_abs, "/a", {"/a/b", "/a/c"}),
        (paths_rel, "root", {"root/a", "root/d"}),
        (paths_rel, "root/a", {"root/a/b", "root/a/c"}),
        (paths_remote, "http://", {"http://a.com", "http://d.com"}),
        (paths_remote, "http://a.com", {"http://a.com/b", "http://a.com/c"}),
    ],
)
def test_immediate(paths, dir_path, expected):
    tree = path_utils.DirTree(paths)
    assert tree.immediate(dir_path) == expected


@pytest.mark.parametrize(
    "paths,dir_path,n,expected",
    [
        (paths_abs, "/", 1, {"/a", "/d"}),
        (paths_abs, "/", 2, {"/a/b", "/a/c"}),
        (paths_rel, "root", 1, {"root/a", "root/d"}),
        (paths_rel, "root", 2, {"root/a/b", "root/a/c"}),
        (paths_remote, "http://", 1, {"http://a.com", "http://d.com"}),
        (paths_remote, "http://", 2, {"http://a.com/b", "http://a.com/c"}),
    ],
)
def test_n_level(paths, dir_path, n, expected):
    tree = path_utils.DirTree(paths)
    assert tree.n_level(dir_path, n) == expected


@pytest.mark.parametrize(
    "paths,dir_path,expected",
    [
        (paths_abs, "/", {"/a", "/a/b", "/a/c", "/d"}),
        (paths_abs, "/a", {"/a/b", "/a/c"}),
        (paths_rel, "root", {"root/a", "root/a/b", "root/a/c", "root/d"}),
        (paths_rel, "root/a", {"root/a/b", "root/a/c"}),
        (paths_remote, "http://", {"http://a.com", "http://a.com/b", "http://a.com/c", "http://d.com"}),
        (paths_remote, "http://a.com/", {"http://a.com/b", "http://a.com/c"}),
    ],
)
def test_recursive(paths, dir_path, expected):
    tree = path_utils.DirTree(paths)
    assert tree.recursive(dir_path) == expected


@pytest.mark.parametrize(
    "paths,dir_path,expected",
    [
        (paths_abs + paths_rel + paths_remote, "/a", {"/a/b", "/a/c"}),
        (paths_abs + paths_rel + paths_remote, "http://a.com", {"http://a.com/b", "http://a.com/c"}),
    ],
)
def test_two_roots(paths, dir_path, expected):
    tree = path_utils.DirTree(paths)
    assert tree.recursive(dir_path) == expected


@pytest.mark.parametrize(
    "paths,dir_path,expected",
    [
        ([ "http://a.com/c/file4"], "http://a.com/c/", set()),  # file
        ([ "http://a.com/c/file4/"], "http://a.com/c/", {"http://a.com/c/file4"}),  # folder
    ],
)
def test_http_folders(paths, dir_path, expected):
    tree = path_utils.DirTree(paths)
    assert tree.immediate(dir_path) == expected
