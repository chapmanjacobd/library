import os, shlex
from pathlib import Path

import pytest

from tests.conftest import generate_file_tree_dict
from xklb.__main__ import library as lb
from xklb.utils import arggroups, devices, objects


@pytest.mark.parametrize("file_over_file", objects.class_enum(arggroups.FileOverFile))
def test_file_over_file(file_over_file, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "5"})
    dest = temp_file_tree({"file4.txt": "4"})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_inodes = generate_file_tree_dict(dest, inodes=False)

    cmd = ["merge-mv"]
    cmd += ["--file-over-file", file_over_file]
    cmd += [src1, dest]

    if file_over_file == arggroups.FileOverFile.DELETE_DEST_ASK:
        with pytest.raises(devices.InteractivePrompt):
            lb(cmd)
        return
    else:
        lb(cmd)

    target_inodes = generate_file_tree_dict(dest, inodes=False)
    if file_over_file == arggroups.FileOverFile.SKIP:
        assert target_inodes == dest_inodes
    elif file_over_file == arggroups.FileOverFile.DELETE_SRC:
        assert target_inodes == dest_inodes
    elif file_over_file == arggroups.FileOverFile.DELETE_DEST:
        assert target_inodes == src1_inodes
    elif file_over_file == arggroups.FileOverFile.RENAME_SRC:
        assert target_inodes == {"file4.txt": (0, "4"), "file4_1.txt": (0, "5")}
    elif file_over_file == arggroups.FileOverFile.RENAME_DEST:
        assert target_inodes == {"file4_1.txt": (0, "4"), "file4.txt": (0, "5")}
    else:
        raise NotImplementedError


@pytest.mark.parametrize("file_over_folder", objects.class_enum(arggroups.FileOverFolder))
def test_file_over_folder(file_over_folder, temp_file_tree):
    src1 = temp_file_tree({"f1": "1"})
    dest = temp_file_tree({"f1": {"file2": "2"}})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_inodes = generate_file_tree_dict(dest, inodes=False)

    cmd = ["merge-mv"]
    cmd += ["--file-over-file", "skip"]
    cmd += ["--file-over-folder", file_over_folder]
    cmd += [src1, dest]
    lb(cmd)

    target_inodes = generate_file_tree_dict(dest, inodes=False)
    if file_over_folder == arggroups.FileOverFolder.SKIP:
        assert target_inodes == dest_inodes
    elif file_over_folder == arggroups.FileOverFolder.DELETE_SRC:
        assert target_inodes == dest_inodes
    elif file_over_folder == arggroups.FileOverFolder.DELETE_DEST:
        assert target_inodes == src1_inodes
    elif file_over_folder == arggroups.FileOverFolder.RENAME_SRC:
        assert target_inodes == {"f1": {"file2": (0, "2")}, "f1_1": (0, "1")}
    elif file_over_folder == arggroups.FileOverFolder.RENAME_DEST:
        assert target_inodes == {"f1_1": {"file2": (0, "2")}, "f1": (0, "1")}
    elif file_over_folder == arggroups.FileOverFolder.MERGE:
        assert target_inodes == {"f1": {"file2": (0, "2"), "f1": (0, "1")}}
    else:
        raise NotImplementedError


@pytest.mark.parametrize("folder_over_file", objects.class_enum(arggroups.FolderOverFile))
def test_folder_over_file(folder_over_file, temp_file_tree):
    src1 = temp_file_tree({"f1": {"file2": "2"}})
    dest = temp_file_tree({"f1": "1"})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_inodes = generate_file_tree_dict(dest, inodes=False)

    cmd = ["merge-mv"]
    cmd += ["--file-over-file", "skip"]
    cmd += ["--folder-over-file", folder_over_file]
    cmd += [src1, dest]
    lb(cmd)

    target_inodes = generate_file_tree_dict(dest, inodes=False)
    if folder_over_file == arggroups.FolderOverFile.SKIP:
        assert target_inodes == dest_inodes
    elif folder_over_file == arggroups.FolderOverFile.DELETE_SRC:
        assert target_inodes == dest_inodes
    elif folder_over_file == arggroups.FolderOverFile.DELETE_DEST:
        assert target_inodes == src1_inodes
    elif folder_over_file == arggroups.FolderOverFile.RENAME_DEST:
        assert target_inodes == {"f1_1": (0, "1"), "f1": {"file2": (0, "2")}}
    elif folder_over_file == arggroups.FolderOverFile.MERGE:
        assert target_inodes == {"f1": {"f1": (0, "1"), "file2": (0, "2")}}
    else:
        raise NotImplementedError


simple_file_tree = {
    "folder1": {"file1.txt": "1", "file4.txt": {"file2.txt": "2"}},
    "folder2": {".hidden": "3"},
    "file4.txt": "4",
}


@pytest.mark.parametrize(
    "mode",
    [
        '--file-over-file "delete-dest-hash rename-src"',
        "--file-over-file delete-dest",
        "--file-over-file skip",
    ],
)
@pytest.mark.parametrize("src_type", ["folder", "folder_bsd", "file", "file_bsd", "not_exist"])
@pytest.mark.parametrize("dest_type", ["not_exist", "folder_merge", "clobber_folder", "clobber_file"])
def test_merge(mode, src_type, dest_type, temp_file_tree):
    if dest_type == "clobber_folder" and src_type != "file":
        return  # not useful to test

    if src_type == "not_exist":
        src1 = temp_file_tree({})
    elif src_type in ("file", "file_bsd"):
        src1 = temp_file_tree({"file4.txt": "5"}) + os.sep + "file4.txt"
    else:  # folder, folder_bsd
        src1 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
        if src_type == "folder":
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

    cmd = ["merge-mv"]
    if mode:
        cmd += shlex.split(mode)
    if src_type == "file_bsd":
        cmd += ["--parent"]
    if src_type == "folder_bsd":
        cmd += ["--bsd"]
    cmd += [src1, dest]
    lb(cmd)

    target_inodes = generate_file_tree_dict(dest, inodes=False)
    if src_type == "not_exist":
        assert target_inodes == dest_inodes
    elif src_type == "folder_bsd" and dest_type == "not_exist":
        assert target_inodes == {Path(src1).name: src1_inodes}
    elif src_type == "file_bsd" and dest_type == "not_exist":
        assert target_inodes == {Path(src1).parent.name: src1_inodes}
    elif dest_type in ("not_exist",):
        assert target_inodes == src1_inodes

    elif src_type == "folder_bsd" and dest_type == "folder_merge":
        assert target_inodes == dest_inodes | {Path(src1).name: src1_inodes}
    elif src_type == "file_bsd" and dest_type == "folder_merge":
        assert target_inodes == dest_inodes | {Path(src1).parent.name: src1_inodes}

    elif dest_type == "folder_merge" and mode == "--file-over-file delete-dest":
        assert target_inodes == dest_inodes | src1_inodes
    elif dest_type == "folder_merge" and "rename-src" in mode:
        assert target_inodes == dest_inodes | {"file4_1.txt": (0, "5")}
    elif dest_type == "folder_merge":
        assert target_inodes == dest_inodes

    elif dest_type == "clobber_folder":
        dest_inodes["file4.txt"] = dest_inodes["file4.txt"] | src1_inodes  # type: ignore
        assert target_inodes == dest_inodes

    elif src_type == "folder_bsd" and dest_type == "clobber_file":
        assert target_inodes == {Path(src1).name: src1_inodes, "file4.txt": (0, "4")}
    elif src_type == "file_bsd" and dest_type == "clobber_file" and mode == "--file-over-file skip":
        assert target_inodes == dest_inodes | {Path(src1).parent.name: src1_inodes}
    elif src_type == "file_bsd" and dest_type == "clobber_file":
        assert target_inodes == dest_inodes | {Path(src1).parent.name: src1_inodes}
    elif (
        src_type == "file"
        and dest_type == "clobber_file"
        and mode in ["--file-over-file skip", '--file-over-file "delete-dest-hash rename-src"']
    ):
        assert target_inodes == dest_inodes
    elif src_type == "file" and dest_type == "clobber_file":
        assert target_inodes == {"file4.txt": (0, "5")}
    elif dest_type == "clobber_file" and mode == "--file-over-file skip":
        assert target_inodes == src1_inodes | {"file4.txt": (0, "4")}
    elif dest_type == "clobber_file" and mode == '--file-over-file "delete-dest-hash rename-src"':
        assert target_inodes == src1_inodes | {"file4.txt": (0, "4"), "file4_1.txt": (0, "5")}
    elif dest_type == "clobber_file":
        assert target_inodes == src1_inodes | {"file4.txt": (0, "5")}

    else:
        raise NotImplementedError


@pytest.mark.parametrize("subcommand", ["merge-mv", "merge-cp"])
def test_merge_two_simple_folders(subcommand, temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    src1_inodes = generate_file_tree_dict(src1, inodes=subcommand == "merge-mv")
    src2_inodes = generate_file_tree_dict(src2, inodes=subcommand == "merge-mv")

    target = temp_file_tree({})
    lb([subcommand, "--bsd", src1, src2, target])

    if subcommand == "merge-cp":
        assert generate_file_tree_dict(src1, inodes=False) == src1_inodes
        assert generate_file_tree_dict(src2, inodes=False) == src2_inodes
    else:
        assert not os.path.exists(src1)
        assert not os.path.exists(src2)

    expected = {Path(src1).name: src1_inodes} | {Path(src2).name: src2_inodes}
    assert generate_file_tree_dict(target, inodes=subcommand == "merge-mv") == expected


def test_simulate(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree) + os.sep
    src2 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    src1_inodes = generate_file_tree_dict(src1)
    src2_inodes = generate_file_tree_dict(src2)

    dest = temp_file_tree({})
    lb(["merge-mv", "--simulate", "--bsd", src1, src2, dest])

    # must not modify except for empty folders needed to test clobbering
    assert generate_file_tree_dict(src1) == src1_inodes
    assert generate_file_tree_dict(src2) == src2_inodes
    assert generate_file_tree_dict(dest) == {
        "folder2": {},
        "folder1": {"file4.txt": {}},
        Path(src2).name: {"folder2": {}, "folder1": {"file4.txt": {}}},
    }


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
