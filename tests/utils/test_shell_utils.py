import argparse, errno
from unittest.mock import patch

import pytest

from library.folders import merge_mv
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
def test_rename_move_file_permission_error(mock_move, caplog):
    mock_move.side_effect = PermissionError
    # Should log warning and not raise
    shell_utils.rename_move_file("src", "dst")
    assert "PermissionError. dst" in caplog.text


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


@patch("shutil.move")
def test_rename_move_file_os_error_logs_and_returns_none(mock_move, caplog):
    mock_move.side_effect = OSError(errno.EIO, "Input/output error")

    with patch("os.path.isfile", return_value=False):
        assert shell_utils.rename_move_file("src", "dst") is None

    assert "Input/output error. src" in caplog.text


@patch("shutil.move")
def test_rename_move_file_os_error_cleans_partial_dest(mock_move):
    mock_move.side_effect = OSError(errno.EIO, "Input/output error")

    with (
        patch("os.path.isfile", return_value=True),
        patch("os.unlink") as mock_unlink,
    ):
        shell_utils.rename_move_file("src", "dst")

    mock_unlink.assert_called_once_with("dst")


@patch("shutil.move")
def test_rename_move_file_enospc_raises_after_logging_and_cleanup(mock_move, caplog):
    mock_move.side_effect = OSError(errno.ENOSPC, "No space left on device")

    with (
        patch("os.path.isfile", return_value=True),
        patch("os.unlink") as mock_unlink,
        pytest.raises(OSError, match="No space left on device"),
    ):
        shell_utils.rename_move_file("src", "dst")

    mock_unlink.assert_called_once_with("dst")
    assert "No space left on device. dst" in caplog.text


@patch("library.folders.merge_mv.log.debug")
@patch("library.folders.merge_mv.shell_utils.rename_move_file")
def test_mmv_file_does_not_log_moved_when_move_fails(mock_move, mock_debug):
    mock_move.return_value = None

    assert merge_mv.mmv_file(argparse.Namespace(simulate=False, verbose=0), "src", "dst") is False
    mock_debug.assert_not_called()


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


@patch("shutil.copy2")
def test_copy_file_os_error_cleans_partial_dest(mock_copy):
    mock_move_error = OSError(errno.EIO, "Input/output error")
    mock_copy.side_effect = mock_move_error

    with (
        patch("os.path.isfile", return_value=True),
        patch("os.unlink") as mock_unlink,
        pytest.raises(OSError, match="Input/output error"),
    ):
        shell_utils.copy_file("src", "dst")

    mock_unlink.assert_called_once_with("dst")


@patch("shutil.copy2")
def test_copy_file_retry_os_error_cleans_partial_dest(mock_copy):
    mock_copy.side_effect = [
        OSError(errno.ENOENT, "No such file or directory"),
        OSError(errno.EIO, "Input/output error"),
    ]

    with (
        patch("os.makedirs"),
        patch("os.path.isfile", return_value=True),
        patch("os.unlink") as mock_unlink,
        pytest.raises(OSError, match="Input/output error"),
    ):
        shell_utils.copy_file("src", "dst")

    mock_unlink.assert_called_once_with("dst")


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


class FakeDirEntry:
    def __init__(self, path, *, is_dir=False, is_symlink=False):
        self.path = path
        self.name = path.rsplit("/", 1)[-1]
        self._is_dir = is_dir
        self._is_symlink = is_symlink

    def is_dir(self, **_kwargs):
        return self._is_dir

    def is_symlink(self):
        return self._is_symlink


class FakeScandir:
    def __init__(self, entries=None, error=None):
        self.entries = iter(entries or [])
        self.error = error

    def __next__(self):
        if self.error is not None:
            raise self.error
        return next(self.entries)

    def __iter__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_rglob_gen_warns_and_skips_eio(caplog):
    def fake_scandir(path):
        if path == "/base":
            return FakeScandir(
                [
                    FakeDirEntry("/base/good_dir", is_dir=True),
                    FakeDirEntry("/base/bad_dir", is_dir=True),
                    FakeDirEntry("/base/root.txt"),
                ]
            )
        if path == "/base/bad_dir":
            return FakeScandir(error=OSError(errno.EIO, "Input/output error"))
        if path == "/base/good_dir":
            return FakeScandir([FakeDirEntry("/base/good_dir/nested.txt")])
        msg = f"unexpected path: {path}"
        raise AssertionError(msg)

    with patch("os.scandir", side_effect=fake_scandir):
        assert list(shell_utils.rglob_gen("/base")) == ["/base/root.txt", "/base/good_dir/nested.txt"]

    assert "Skipping folder /base/bad_dir" in caplog.text


def test_rglob_warns_and_skips_eio(caplog):
    def fake_scandir(path):
        if path == "/base":
            return FakeScandir(
                [
                    FakeDirEntry("/base/good_dir", is_dir=True),
                    FakeDirEntry("/base/bad_dir", is_dir=True),
                    FakeDirEntry("/base/root.txt"),
                ]
            )
        if path == "/base/bad_dir":
            return FakeScandir(error=OSError(errno.EIO, "Input/output error"))
        if path == "/base/good_dir":
            return FakeScandir([FakeDirEntry("/base/good_dir/nested.txt")])
        msg = f"unexpected path: {path}"
        raise AssertionError(msg)

    with patch("os.scandir", side_effect=fake_scandir):
        files, _filtered_files, folders = shell_utils.rglob("/base", quiet=True)

    assert files == {"/base/root.txt", "/base/good_dir/nested.txt"}
    assert folders == {"/base/good_dir", "/base/bad_dir"}
    assert "Skipping folder /base/bad_dir" in caplog.text
