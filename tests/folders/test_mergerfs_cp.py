import os, tempfile
from pathlib import Path

import pytest

from tests.conftest import generate_file_tree_dict
from library.__main__ import library as lb
from library.utils import consts, objects, path_utils

simple_file_tree = {
    "folder1": {"file1.txt": "1", "file4.txt": {"file2.txt": "2"}},
    "folder2": {".hidden": "3"},
    "file4.txt": "4",
}

pytestmark = pytest.mark.skipif(not consts.IS_LINUX, reason="Skip Windows / Mac")


@pytest.fixture(autouse=True)
def _mock_get_mergerfs_mounts(monkeypatch):
    from library.folders import mergerfs_cp

    temp_dir = tempfile.gettempdir()
    monkeypatch.setattr(mergerfs_cp, "get_mergerfs_mounts", lambda: [temp_dir])
    monkeypatch.setattr(mergerfs_cp, "get_srcmounts", lambda _: [temp_dir])


@pytest.mark.parametrize("src_type", ["folder", "folder_bsd", "file", "not_exist"])
@pytest.mark.parametrize("dest_type", ["not_exist", "folder_merge", "clobber_file", "clobber_folder"])
def test_merge(assert_unchanged, src_type, dest_type, temp_file_tree):
    if src_type == "not_exist":
        src1 = temp_file_tree({})
    elif src_type in ("file", "parent"):
        src1 = temp_file_tree({"file4.txt": "5"})
    else:  # folder, bsd
        src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})

    src1_arg = src1
    if src_type in ("file", "parent"):
        src1_arg = src1 + os.sep + "file4.txt"
    elif src_type == "folder":
        src1_arg = src1 + os.sep

    if dest_type == "not_exist":
        dest = temp_file_tree({})
    else:
        dest = temp_file_tree(simple_file_tree)

    dest_arg = dest
    if dest_type == "clobber_file":
        dest_arg = os.path.join(dest, "file4.txt")
    elif dest_type == "clobber_folder":
        dest_arg = os.path.join(dest, "folder1")

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_before = generate_file_tree_dict(dest, inodes=False)
    dest_before = objects.replace_key_in_dict(dest_before, path_utils.basename(dest), "dest")

    cmd = ["mergerfs-cp"]
    cmd += ["--file-over-file", "delete-dest"]
    if src_type == "folder_bsd":
        cmd += ["--bsd"]
    if dest_type == "clobber_file":
        cmd += ["--dest-file"]
    lb([*cmd, src1_arg, dest_arg])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes

    dest_after = generate_file_tree_dict(dest, inodes=False)
    dest_after = objects.replace_keys_in_dict(
        dest_after, {path_utils.basename(src1): "src1", path_utils.basename(dest): "dest"}
    )

    assert_unchanged(
        {
            "dest_before": dest_before,
            "command": " ".join(
                [
                    *cmd,
                    f"{src1_arg.replace(src1, '/src1').replace(os.sep,'/')}:{src_type}",
                    f"{dest_arg.replace(dest, '/dest').replace(os.sep,'/')}:{dest_type}",
                ]
            ),
            "dest_after": dest_after,
        }
    )


def test_dupe_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["mergerfs-cp", "--parent", src1, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | {Path(src1).name: src1_inodes}


def test_file_replace(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["mergerfs-cp", "--file-over-file", "delete-dest", os.path.join(src1, "file4.txt"), target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | src1_inodes


def test_file_replace_file(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    target = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    target_inodes = generate_file_tree_dict(target, inodes=False)
    lb(
        [
            "mergerfs-cp",
            "--file-over-file",
            "delete-dest",
            os.path.join(src1, "file4.txt"),
            os.path.join(target, "file4.txt"),
        ]
    )

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == target_inodes | src1_inodes


def test_dupe_replace_tree(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    dest = temp_file_tree(simple_file_tree)

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_inodes = generate_file_tree_dict(dest, inodes=False)
    lb(["mergerfs-cp", "--file-over-file", "delete-dest", src1 + os.sep, dest])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(dest, inodes=False) == dest_inodes | src1_inodes


def test_folder_conflict_replace(temp_file_tree):
    src1 = temp_file_tree({"file1": "5"})
    target = temp_file_tree({"file1": {"file1": "4"}})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_inodes = generate_file_tree_dict(target, inodes=False)
    lb(["mergerfs-cp", src1 + os.sep, target])

    assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
    assert generate_file_tree_dict(target, inodes=False) == {"file1": {"file1_1": "4", "file1": "5"}}
