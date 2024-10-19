import pytest

from tests.conftest import generate_file_tree_dict
from xklb.__main__ import library as lb
from xklb.utils import arggroups, devices, objects


@pytest.mark.parametrize("file_over_file", objects.class_enum(arggroups.FileOverFile))
def test_file_over_file_mod_start(file_over_file, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "5", "folder1": {"file2.txt": "5", "folder2": {"file3.txt": "5"}}})
    dest = temp_file_tree({"file4.txt": "4"})

    cmd = ["merge-mv", "--modify-depth", "1"]
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
        assert target_inodes == {"file4.txt": "4", "file2.txt": "5", "folder2": {"file3.txt": "5"}}
    elif file_over_file == arggroups.FileOverFile.DELETE_SRC:
        assert target_inodes == {"file4.txt": "4", "file2.txt": "5", "folder2": {"file3.txt": "5"}}
    elif file_over_file == arggroups.FileOverFile.DELETE_DEST:
        assert target_inodes == {"file4.txt": "5", "file2.txt": "5", "folder2": {"file3.txt": "5"}}
    elif file_over_file == arggroups.FileOverFile.RENAME_SRC:
        assert target_inodes == {
            "file4.txt": "4",
            "file4_1.txt": "5",
            "file2.txt": "5",
            "folder2": {"file3.txt": "5"},
        }
    elif file_over_file == arggroups.FileOverFile.RENAME_DEST:
        assert target_inodes == {
            "file4_1.txt": "4",
            "file4.txt": "5",
            "file2.txt": "5",
            "folder2": {"file3.txt": "5"},
        }
    else:
        raise NotImplementedError


@pytest.mark.parametrize("file_over_file", objects.class_enum(arggroups.FileOverFile))
def test_file_over_file_mod_end(file_over_file, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "5", "folder1": {"file2.txt": "5", "folder2": {"file3.txt": "5"}}})
    dest = temp_file_tree({"file4.txt": "4"})

    cmd = ["merge-mv", "--modify-depth", ":1"]
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
        assert target_inodes == {"file4.txt": "4", "folder1": {"file2.txt": "5", "file3.txt": "5"}}
    elif file_over_file == arggroups.FileOverFile.DELETE_SRC:
        assert target_inodes == {"file4.txt": "4", "folder1": {"file2.txt": "5", "file3.txt": "5"}}
    elif file_over_file == arggroups.FileOverFile.DELETE_DEST:
        assert target_inodes == {"file4.txt": "5", "folder1": {"file2.txt": "5", "file3.txt": "5"}}
    elif file_over_file == arggroups.FileOverFile.RENAME_SRC:
        assert target_inodes == {
            "file4.txt": "4",
            "file4_1.txt": "5",
            "folder1": {"file2.txt": "5", "file3.txt": "5"},
        }
    elif file_over_file == arggroups.FileOverFile.RENAME_DEST:
        assert target_inodes == {
            "file4_1.txt": "4",
            "file4.txt": "5",
            "folder1": {"file2.txt": "5", "file3.txt": "5"},
        }
    else:
        raise NotImplementedError


@pytest.mark.parametrize("file_over_file", objects.class_enum(arggroups.FileOverFile))
def test_file_over_file_mod_rev(file_over_file, temp_file_tree):
    src1 = temp_file_tree({"file4.txt": "5", "folder1": {"file2.txt": "5", "folder2": {"file3.txt": "5"}}})
    dest = temp_file_tree({"file4.txt": "4"})

    cmd = ["merge-mv", "--modify-depth", "::-1"]
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
        assert target_inodes == {
            "file4.txt": "4",
            "folder1": {"file2.txt": "5"},
            "folder2": {"folder1": {"file3.txt": "5"}},
        }
    elif file_over_file == arggroups.FileOverFile.DELETE_SRC:
        assert target_inodes == {
            "file4.txt": "4",
            "folder1": {"file2.txt": "5"},
            "folder2": {"folder1": {"file3.txt": "5"}},
        }
    elif file_over_file == arggroups.FileOverFile.DELETE_DEST:
        assert target_inodes == {
            "file4.txt": "5",
            "folder1": {"file2.txt": "5"},
            "folder2": {"folder1": {"file3.txt": "5"}},
        }
    elif file_over_file == arggroups.FileOverFile.RENAME_SRC:
        assert target_inodes == {
            "file4.txt": "4",
            "file4_1.txt": "5",
            "folder1": {"file2.txt": "5"},
            "folder2": {"folder1": {"file3.txt": "5"}},
        }
    elif file_over_file == arggroups.FileOverFile.RENAME_DEST:
        assert target_inodes == {
            "file4_1.txt": "4",
            "file4.txt": "5",
            "folder1": {"file2.txt": "5"},
            "folder2": {"folder1": {"file3.txt": "5"}},
        }
    else:
        raise NotImplementedError


@pytest.mark.parametrize("folder_over_file", objects.class_enum(arggroups.FolderOverFile))
def test_folder_over_file(folder_over_file, temp_file_tree):
    src1 = temp_file_tree({"f1": {"f1": {"file2": "2"}}})
    dest = temp_file_tree({"f1": "1"})

    src1_inodes = generate_file_tree_dict(src1, inodes=False)
    dest_inodes = generate_file_tree_dict(dest, inodes=False)

    cmd = ["merge-mv", "--modify-depth", "1"]
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
        assert target_inodes == src1_inodes["f1"]
    elif folder_over_file == arggroups.FolderOverFile.RENAME_DEST:
        assert target_inodes == {"f1_1": "1", "f1": {"file2": "2"}}
    elif folder_over_file == arggroups.FolderOverFile.MERGE:
        assert target_inodes == {"f1": {"f1": "1", "file2": "2"}}
    else:
        raise NotImplementedError
