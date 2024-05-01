import pytest

from xklb.folders.rel_mv import gen_rel_path


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
