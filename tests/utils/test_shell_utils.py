from unittest.mock import patch

import pytest

from library.utils import shell_utils


def test_rename_move_file_simulate(capsys):
    shell_utils.rename_move_file("src", "dst", simulate=True)
    captured = capsys.readouterr()
    assert "mv src dst" in captured.out


@patch("shutil.move")
def test_rename_move_file_success(mock_move):
    shell_utils.rename_move_file("src", "dst")
    mock_move.assert_called_once_with("src", "dst")


@patch("shutil.move")
def test_rename_move_file_permission_error(mock_move):
    mock_move.side_effect = PermissionError
    # Should log warning and not raise
    shell_utils.rename_move_file("src", "dst")


@patch("shutil.move")
def test_rename_move_file_file_not_found_error(mock_move):
    mock_move.side_effect = OSError(2, "No such file or directory")

    with patch("os.path.exists", return_value=True), patch("os.makedirs"):
        # reset recursion limit to avoid infinite if logic is wrong?
        # Actually logic is: if ENOENT, check src exists.
        # If we mock move to fail again, it will loop.
        # So we mock move to succeed on second call
        mock_move.side_effect = [OSError(2, "No such file or directory"), None]
        shell_utils.rename_move_file("src", "parent/dst")
        assert mock_move.call_count == 2


def test_rename_no_replace(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.touch()

    shell_utils.rename_no_replace(str(src), str(dst))
    assert dst.exists()
    assert not src.exists()

    src.touch()
    with pytest.raises(FileExistsError):
        shell_utils.rename_no_replace(str(src), str(dst))


def test_scan_stats():
    assert shell_utils.scan_stats(10, 0, 5, 0) == "Files: 10 Folders: 5"
    assert "ignored" in shell_utils.scan_stats(10, 2, 5, 1)


def test_resolve_absolute_path(tmp_path):
    f = tmp_path / "test"
    f.touch()
    assert shell_utils.resolve_absolute_path(str(f)) == str(f.resolve())
    assert shell_utils.resolve_absolute_path("relative") == "relative"


@patch("shutil.copy2")
def test_copy_file_simulate(mock_copy, capsys):
    shell_utils.copy_file("src", "dst", simulate=True)
    captured = capsys.readouterr()
    assert "cp src dst" in captured.out
    mock_copy.assert_not_called()


@patch("shutil.copy2")
def test_copy_file_success(mock_copy):
    shell_utils.copy_file("src", "dst")
    mock_copy.assert_called_once_with("src", "dst")


def test_flatten_wrapper_folder(tmp_path):
    # struct: output_path/wrapper/file.txt
    output_path = tmp_path / "out"
    output_path.mkdir()
    wrapper = output_path / "wrapper"
    wrapper.mkdir()
    file = wrapper / "file.txt"
    file.touch()

    shell_utils.flatten_wrapper_folder(str(output_path))

    assert (output_path / "file.txt").exists()
    assert not wrapper.exists()
