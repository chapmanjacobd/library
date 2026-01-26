import os
from pathlib import Path

import pytest

from library.__main__ import library as lb
from library.utils import arggroups, consts, devices, objects, path_utils
from tests.conftest import read_relative_file_tree_dict


@pytest.mark.parametrize("file_over_file", objects.class_enum(arggroups.FileOverFile))
def test_file_over_file(file_over_file, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "5"})
    dest = temp_file_tree({"file4.txt": "4"})

    src1_inodes = read_relative_file_tree_dict(src1, inodes=False)
    dest_inodes = read_relative_file_tree_dict(dest, inodes=False)

    cmd = ["merge-mv"]
    cmd += ["--file-over-file", file_over_file]
    cmd += [src1, dest]

    if file_over_file == arggroups.FileOverFile.DELETE_DEST_ASK:
        with pytest.raises(devices.InteractivePrompt):
            lb(cmd)
        return
    else:
        lb(cmd)

    target_inodes = read_relative_file_tree_dict(dest, inodes=False)
    if file_over_file == arggroups.FileOverFile.SKIP:
        assert target_inodes == dest_inodes
    elif file_over_file == arggroups.FileOverFile.DELETE_SRC:
        assert target_inodes == dest_inodes
    elif file_over_file == arggroups.FileOverFile.DELETE_DEST:
        assert target_inodes == src1_inodes
    elif file_over_file == arggroups.FileOverFile.RENAME_SRC:
        assert target_inodes == {"file4.txt": "4", "file4_1.txt": "5"}
    elif file_over_file == arggroups.FileOverFile.RENAME_DEST:
        assert target_inodes == {"file4_1.txt": "4", "file4.txt": "5"}
    else:
        raise NotImplementedError


@pytest.mark.parametrize("file_over_folder", objects.class_enum(arggroups.FileOverFolder))
def test_file_over_folder(file_over_folder, temp_file_tree):
    src1 = temp_file_tree({"f1": "1"})
    dest = temp_file_tree({"f1": {"file2": "2"}})

    src1_inodes = read_relative_file_tree_dict(src1, inodes=False)
    dest_inodes = read_relative_file_tree_dict(dest, inodes=False)

    cmd = ["merge-mv"]
    cmd += ["--file-over-file", "skip"]
    cmd += ["--file-over-folder", file_over_folder]
    cmd += [src1, dest]
    lb(cmd)

    target_inodes = read_relative_file_tree_dict(dest, inodes=False)
    if file_over_folder == arggroups.FileOverFolder.SKIP:
        assert target_inodes == dest_inodes
    elif file_over_folder == arggroups.FileOverFolder.DELETE_SRC:
        assert target_inodes == dest_inodes
    elif file_over_folder == arggroups.FileOverFolder.DELETE_DEST:
        assert target_inodes == src1_inodes
    elif file_over_folder == arggroups.FileOverFolder.RENAME_SRC:
        assert target_inodes == {"f1": {"file2": "2"}, "f1_1": "1"}
    elif file_over_folder == arggroups.FileOverFolder.RENAME_DEST:
        assert target_inodes == {"f1_1": {"file2": "2"}, "f1": "1"}
    elif file_over_folder == arggroups.FileOverFolder.MERGE:
        assert target_inodes == {"f1": {"file2": "2", "f1": "1"}}
    else:
        raise NotImplementedError


@pytest.mark.parametrize("folder_over_file", objects.class_enum(arggroups.FolderOverFile))
def test_folder_over_file(folder_over_file, temp_file_tree):
    src1 = temp_file_tree({"f1": {"file2": "2"}})
    dest = temp_file_tree({"f1": "1"})

    src1_inodes = read_relative_file_tree_dict(src1, inodes=False)
    dest_inodes = read_relative_file_tree_dict(dest, inodes=False)

    cmd = ["merge-mv"]
    cmd += ["--file-over-file", "skip"]
    cmd += ["--folder-over-file", folder_over_file]
    cmd += [src1, dest]
    lb(cmd)

    target_inodes = read_relative_file_tree_dict(dest, inodes=False)
    if folder_over_file == arggroups.FolderOverFile.SKIP:
        assert target_inodes == dest_inodes
    elif folder_over_file == arggroups.FolderOverFile.DELETE_SRC:
        assert target_inodes == dest_inodes
    elif folder_over_file == arggroups.FolderOverFile.DELETE_DEST:
        assert target_inodes == src1_inodes
    elif folder_over_file == arggroups.FolderOverFile.RENAME_DEST:
        assert target_inodes == {"f1_1": "1", "f1": {"file2": "2"}}
    elif folder_over_file == arggroups.FolderOverFile.MERGE:
        assert target_inodes == {"f1": {"f1": "1", "file2": "2"}}
    else:
        raise NotImplementedError


simple_file_tree = {
    "folder1": {"file1.txt": "1", "file4.txt": {"file2.txt": "2"}},
    "folder2": {".hidden": "3"},
    "file4.txt": "4",
}


@pytest.mark.parametrize("src_type", ["folder", "bsd", "file", "parent", "not_exist"])
@pytest.mark.parametrize("dest_type", ["not_exist", "folder_merge", "clobber_folder", "clobber_file"])
@pytest.mark.parametrize("dest_opt", ["folder", "bsd", "file"])
@pytest.mark.parametrize("file_over_file_mode", ["delete-dest-hash rename-src", "delete-dest", "skip"])
def test_merge(assert_unchanged, src_type, dest_type, dest_opt, file_over_file_mode, temp_file_tree):
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

    cmd = ["merge-mv", "--file-over-file", file_over_file_mode]
    if src_type == "parent":
        cmd += ["--parent"]
    if src_type == "bsd":
        cmd += ["--bsd"]

    if dest_opt == "folder":
        cmd += ["--dest-folder"]
    elif dest_opt == "bsd":
        cmd += ["--dest-bsd"]
    elif dest_opt == "file":
        cmd += ["--dest-file"]

    src1_before = read_relative_file_tree_dict(src1, inodes=False)
    src1_before = objects.replace_key_in_dict(src1_before, path_utils.basename(src1), "src1")
    dest_before = read_relative_file_tree_dict(dest, inodes=False)
    dest_before = objects.replace_key_in_dict(dest_before, path_utils.basename(dest), "dest")

    lb([*cmd, src1_arg, dest_arg])

    if os.path.exists(src1):
        src1_after = read_relative_file_tree_dict(src1, inodes=False)
    else:
        src1_after = {}
    src1_after = objects.replace_key_in_dict(src1_after, path_utils.basename(src1), "src1")
    dest_after = read_relative_file_tree_dict(dest, inodes=False)
    dest_after = objects.replace_keys_in_dict(
        dest_after, {path_utils.basename(src1): "src1", path_utils.basename(dest): "dest"}
    )

    assert_unchanged(
        {
            "src1_before": src1_before,
            "dest_before": dest_before,
            "command": " ".join(
                [
                    *cmd,
                    f"{src1_arg.replace(src1, '/src1').replace(os.sep,'/')}:{src_type}",
                    f"{dest_arg.replace(dest, '/dest').replace(os.sep,'/')}:{dest_type}",
                ]
            ),
            "src1_after": src1_after,
            "dest_after": dest_after,
        }
    )


@pytest.mark.parametrize("subcommand", ["merge-mv", "merge-cp"])
def test_merge_two_simple_folders(subcommand, temp_file_tree):
    src1 = temp_file_tree(simple_file_tree)
    src2 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    src1_inodes = read_relative_file_tree_dict(src1, inodes=subcommand == "merge-mv")
    src2_inodes = read_relative_file_tree_dict(src2, inodes=subcommand == "merge-mv")

    target = temp_file_tree({})
    lb([subcommand, "--bsd", src1, src2, target])

    if subcommand == "merge-cp":
        assert read_relative_file_tree_dict(src1, inodes=False) == src1_inodes
        assert read_relative_file_tree_dict(src2, inodes=False) == src2_inodes
    else:
        assert not os.path.exists(src1)
        assert not os.path.exists(src2)

    expected = {Path(src1).name: src1_inodes} | {Path(src2).name: src2_inodes}
    assert read_relative_file_tree_dict(target, inodes=subcommand == "merge-mv") == expected


def test_simulate(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree) + os.sep
    src2 = temp_file_tree(simple_file_tree | {"file4.txt": "5"})
    src1_inodes = read_relative_file_tree_dict(src1)
    src2_inodes = read_relative_file_tree_dict(src2)

    dest = temp_file_tree({})
    lb(["merge-mv", "--simulate", "--bsd", src1, src2, dest])

    # must not modify except for empty folders needed to test clobbering
    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(src2) == src2_inodes
    assert read_relative_file_tree_dict(dest) == {
        "folder2": {},
        "folder1": {"file4.txt": {}},
        Path(src2).name: {"folder2": {}, "folder1": {"file4.txt": {}}},
    }


def test_simulate_mkdirs(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree) + os.sep
    src1_inodes = read_relative_file_tree_dict(src1)

    dest = temp_file_tree({})
    lb(["merge-mv", "--simulate", src1, dest])

    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(dest) == {
        "folder1": {
            "file4.txt": {},
        },
        "folder2": {},
    }


def test_filter_folder(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree) + os.sep
    src1_inodes = read_relative_file_tree_dict(src1)

    dest = temp_file_tree({})
    lb(["merge-mv", "-S+1Gi", src1, dest])

    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(dest) == {}


def test_filter_file(temp_file_tree):
    src1 = temp_file_tree(simple_file_tree) + os.sep
    src1_inodes = read_relative_file_tree_dict(src1)

    dest = temp_file_tree({})
    lb(["merge-mv", "-S+1Gi", src1 + "file4.txt", dest])

    assert read_relative_file_tree_dict(src1) == src1_inodes
    assert read_relative_file_tree_dict(dest) == {}


@pytest.mark.parametrize("subcommand", ["merge-mv", "merge-cp"])
def test_same_file(subcommand, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "4"}) + os.sep + "file4.txt"
    src1_inodes = read_relative_file_tree_dict(src1, inodes=subcommand == "merge-mv")

    lb([subcommand, src1, src1])
    assert read_relative_file_tree_dict(src1, inodes=subcommand == "merge-mv") == src1_inodes


@pytest.mark.parametrize("subcommand", ["merge-mv", "merge-cp"])
def test_same_folder(subcommand, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "4"})
    src1_inodes = read_relative_file_tree_dict(src1)

    lb([subcommand, src1 + os.sep, src1 + os.sep])
    assert read_relative_file_tree_dict(src1) == src1_inodes


def relmv_run(temp_file_tree, src, use_parent, relative_to):
    file_tree = {"file4.txt": "4"}
    src1 = temp_file_tree(file_tree)
    src1_inodes = read_relative_file_tree_dict(src1)

    src1_file = src1 + os.sep + "file4.txt"

    target = temp_file_tree({})
    command = ["merge-mv"]

    if use_parent:
        command += ["--parent"]

    command += ["--relative-to"]
    if relative_to == "TEMP_DIR":
        command += [consts.TEMP_DIR]
    elif relative_to == "SRC_FILE":
        command += [src1_file]
    elif relative_to == "SRC_FOLDER":
        command += [src1]
    elif relative_to == "TARGET":
        command += [target]
    else:
        command += [relative_to]

    if src == "FILE":
        command += [src1_file]
    else:
        command += [src1]

    command += [target]
    lb(command)
    return src1, src1_inodes, target


@pytest.mark.parametrize("src", ["FILE", "FOLDER"])
@pytest.mark.parametrize("use_parent", [True, False])
@pytest.mark.parametrize(
    "relative_to", ["::", "/", os.sep, "TEMP_DIR", "SRC_FILE", "SRC_FOLDER", "SRC_PARENT", "TARGET"]
)
def test_relmv(temp_file_tree, src, use_parent, relative_to):
    src1, src1_inodes, target = relmv_run(temp_file_tree, src, use_parent, relative_to)

    expected_results = path_utils.build_nested_dir_dict(consts.TEMP_DIR, {Path(src1).name: src1_inodes})
    if relative_to in ("::", "TEMP_DIR"):
        expected_results = {Path(src1).name: src1_inodes}
    if relative_to in ("SRC_FOLDER",):
        expected_results = src1_inodes
    if src == "FILE" and relative_to == "SRC_FILE":
        expected_results = {Path(target).name: src1_inodes["file4.txt"]}

    assert read_relative_file_tree_dict(target) == expected_results
