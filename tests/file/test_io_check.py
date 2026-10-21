import errno

from library.file import io_check


def test_check_file_reads_a_regular_file(tmp_path):
    path = tmp_path / "readable"
    path.write_bytes(b"content")

    result = io_check.check_file(path, chunk_size=2)

    assert result.ok
    assert not result.is_io_error


def test_check_file_reports_input_output_errors(monkeypatch, tmp_path):
    path = tmp_path / "unreadable"

    def fail_open(*_args, **_kwargs):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr("builtins.open", fail_open)
    result = io_check.check_file(path)

    assert not result.ok
    assert result.is_io_error
    assert result.path == str(path)


def test_check_file_only_trashes_when_requested(monkeypatch, tmp_path):
    path = tmp_path / "unreadable"
    path.write_bytes(b"content")
    results = [io_check.IOCheckResult(str(path), OSError(errno.EIO, "Input/output error"))]
    args = type("Args", (), {"delete_files": False})()
    trash_calls = []
    monkeypatch.setattr(io_check.shell_utils, "trash", lambda *args, **_kwargs: trash_calls.append(args))

    io_check.trash_io_errors(args, results)

    assert trash_calls == []


def test_trash_io_errors_requires_confirmation(monkeypatch):
    result = io_check.IOCheckResult("unreadable", OSError(errno.EIO, "Input/output error"))
    args = type("Args", (), {"delete_files": True, "simulate": False, "no_confirm": False})()
    trash_calls = []
    monkeypatch.setattr(io_check.devices, "confirm", lambda *_args: True)
    monkeypatch.setattr(io_check.shell_utils, "trash", lambda *args, **_kwargs: trash_calls.append(args))

    io_check.trash_io_errors(args, [result])

    assert trash_calls == [(args, "unreadable")]
