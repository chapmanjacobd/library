import os, shutil, tempfile
from pathlib import Path

import pytest


def create_file_tree(parent_dir, tree):
    for name, contents in tree.items():
        path = Path(parent_dir, name)
        if isinstance(contents, dict):
            os.makedirs(path)
            create_file_tree(path, contents)
        else:
            path.write_text(contents)


@pytest.fixture
def temp_file_tree(request):
    def _create_temp_file_tree(tree):
        temp_dir = tempfile.mkdtemp()
        create_file_tree(temp_dir, tree)
        request.addfinalizer(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        return temp_dir

    return _create_temp_file_tree


@pytest.fixture
def temp_db(request):
    def _create_temp_file_tree():
        temp_dir_fd, temp_dir_name = tempfile.mkstemp(".db")
        request.addfinalizer(lambda: Path(temp_dir_name).unlink())
        return temp_dir_name

    return _create_temp_file_tree


def generate_file_tree_dict(temp_dir):
    def _generate_tree_dict(directory):
        tree_dict = {}
        for item in directory.iterdir():
            if item.is_file():
                with item.open() as file:
                    tree_dict[item.name] = file.read()
            elif item.is_dir():
                tree_dict[item.name] = _generate_tree_dict(item)
        return tree_dict

    base_path = Path(temp_dir)
    return _generate_tree_dict(base_path)


def test_file_tree_creation(temp_file_tree):
    file_tree = {
        "folder1": {"file1.txt": "Content of file 1", "subfolder1": {"file2.txt": "Content of file 2"}},
        "folder2": {"file3.txt": "Content of file 3"},
        "file4.txt": "Content of file 4",
    }

    temp_dir = temp_file_tree(file_tree)

    assert Path(temp_dir).exists()
    assert Path(temp_dir, "file4.txt").read_text() == "Content of file 4"
    assert Path(temp_dir, "folder1", "subfolder1").is_dir()
    assert file_tree == generate_file_tree_dict(temp_dir)

    file_tree = {}
    temp_dir = temp_file_tree(file_tree)
    assert file_tree == generate_file_tree_dict(temp_dir)

    file_tree = {"folder1": {}}
    temp_dir = temp_file_tree(file_tree)
    assert file_tree == generate_file_tree_dict(temp_dir)

    file_tree = {"file4.txt": "Content of file 4"}
    temp_dir = temp_file_tree(file_tree)
    assert file_tree == generate_file_tree_dict(temp_dir)
