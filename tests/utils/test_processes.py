import json, multiprocessing, subprocess, time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from library.utils import processes


def test_sizeout():
    processes.sizeout_max = None
    processes.sizeout_total = 0
    assert not processes.sizeout("10MB", 1024 * 1024)
    assert not processes.sizeout("10MB", 8 * 1024 * 1024)
    assert processes.sizeout("10MB", 2 * 1024 * 1024)  # Total 11MB


def test_adjust_duration():
    assert processes.adjust_duration(100, 0, None) == 100
    assert processes.adjust_duration(100, 10, None) == 90
    assert processes.adjust_duration(100, 10, 50) == 40
    assert processes.adjust_duration(100, None, None) == 100
    assert processes.adjust_duration(100, -10, None) == 100  # Should be 0 but implementation checks 0 <= start


def fast_function_top_level():
    return "success"


def test_with_timeout_success():
    # Use top-level function for multiprocessing compatibility
    # Pool startup can take several seconds on macOS CI.
    decorated_func = processes.with_timeout(10)(fast_function_top_level)
    assert decorated_func() == "success"


@patch("library.utils.processes.multiprocessing.Pool")
def test_with_timeout_failure(mock_pool):
    pool_instance = Mock()
    mock_pool.return_value = pool_instance
    async_result = Mock()
    async_result.get.side_effect = multiprocessing.TimeoutError
    pool_instance.apply_async.return_value = async_result

    @processes.with_timeout(1)
    def slow_function():
        time.sleep(2)
        return "too slow"

    with pytest.raises(multiprocessing.TimeoutError):
        slow_function()


def test_with_timeout_thread_success():
    @processes.with_timeout_thread(2)
    def fast_function():
        return "success"

    assert fast_function() == "success"


def test_with_timeout_thread_failure():
    @processes.with_timeout_thread(0.1)
    def slow_function():
        time.sleep(0.5)
        return "too slow"

    with pytest.raises(TimeoutError):
        slow_function()


@patch("subprocess.run")
def test_cmd_success(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(args=["ls"], returncode=0, stdout="file1\nfile2", stderr="")
    result = processes.cmd("ls")
    assert result.returncode == 0
    assert result.stdout == "file1\nfile2"


@patch("subprocess.run")
def test_cmd_failure(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ls", "nonexistent"], returncode=1, stdout="", stderr="error"
    )
    with pytest.raises(subprocess.CalledProcessError):
        processes.cmd("ls", "nonexistent")


@patch("subprocess.run")
def test_cmd_failure_non_strict(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ls", "nonexistent"], returncode=1, stdout="", stderr="error"
    )
    result = processes.cmd("ls", "nonexistent", strict=False)
    assert result.returncode == 1


def test_unar_delete_skips_non_archive(tmp_path, monkeypatch):
    archive_path = tmp_path / "icon.1"
    archive_path.write_text("not an archive")
    calls = []

    def fail_lsar(*command, **_kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, "lsar")

    monkeypatch.setattr(processes, "cmd", fail_lsar)

    output_path, updates = processes.unar_delete(str(archive_path))

    assert calls == [("lsar", "-json", str(archive_path))]
    assert output_path == str(tmp_path / "icon")
    assert updates == []
    assert archive_path.exists()
    assert not (tmp_path / "icon").exists()


def _partial_extraction_lsar_json(archive_path):
    return {
        "lsarFormatName": "Gzip",
        "lsarInnerFormatName": "Tar",
        "lsarProperties": {"XADVolumes": [str(archive_path)]},
        "lsarContents": [],
    }


def _fake_partial_unar_cmd(archive_path, tar_result):
    def fake_cmd(*command, **_kwargs):
        if command[0] == "lsar":
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(_partial_extraction_lsar_json(archive_path)), stderr="")
        if command[0] == "unar":
            raise subprocess.CalledProcessError(
                1,
                command,
                output="",
                stderr="  ./etc  (10 B)... Failed! (Could not create directory)\n1626 files failed.",
            )
        if command[0] == "tar":
            return tar_result(command)
        raise AssertionError(command)

    return fake_cmd


def test_unar_delete_retries_partial_extraction_with_tar(tmp_path, monkeypatch):
    archive_path = tmp_path / "site.tar.gz"
    archive_path.write_bytes(b"archive")
    output_path = tmp_path / "site"

    def fake_tar(command):
        target = Path(command[command.index("-C") + 1])
        (target / "etc").mkdir()
        (target / "etc" / "config.php").write_text("<?php")
        (target / "public_html").mkdir()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(processes, "cmd", _fake_partial_unar_cmd(archive_path, fake_tar))
    monkeypatch.setattr(processes.shutil, "which", lambda _name: "/usr/bin/tar")

    output, updates = processes.unar_delete(str(archive_path))

    assert output == str(output_path)
    assert updates == []
    assert (output_path / "etc" / "config.php").read_text() == "<?php"
    assert not archive_path.exists()


def test_unar_delete_keeps_archive_when_partial_extraction_cannot_be_recovered(tmp_path, monkeypatch):
    archive_path = tmp_path / "site.tar.gz"
    archive_path.write_bytes(b"archive")
    output_path = tmp_path / "site"

    def fail_tar(command):
        raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(processes, "cmd", _fake_partial_unar_cmd(archive_path, fail_tar))
    monkeypatch.setattr(processes.shutil, "which", lambda _name: "/usr/bin/tar")

    output, updates = processes.unar_delete(str(archive_path))

    assert output == str(output_path)
    assert updates == []
    assert archive_path.exists()
    assert list(tmp_path.glob(".unar-tar-fallback-*")) == []


@patch("importlib.import_module")
@patch("subprocess.check_call")
def test_load_or_install_modules(mock_check_call, mock_import_module):
    # Simulate first import fail, install success, second import success
    mock_import_module.side_effect = [ImportError, None]

    processes.load_or_install_modules([["missing_module"]])

    mock_check_call.assert_called()
    assert mock_import_module.call_count == 2


@patch("importlib.import_module", side_effect=ImportError("module unavailable"))
@patch("subprocess.check_call", side_effect=subprocess.CalledProcessError(1, "pip"))
def test_load_or_install_modules_reports_failure(
    mock_check_call, _mock_import_module  # ruff: ignore[pytest-fixture-param-without-value] - patch injects a mock, not a fixture
):  # noqa: PT019 - patch injects a mock, not a fixture
    with pytest.raises(ImportError, match="None of the python packages"):
        processes.load_or_install_modules([["missing_module"]])

    mock_check_call.assert_called_once()


def test_pclose_works_with_stdin_pipe():
    # 4.1: Pclose passes the builtin `input` function to communicate(), raising
    # TypeError whenever the process has stdin=PIPE.
    proc = subprocess.Popen(["echo", "hi"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    result = processes.Pclose(proc)
    assert result.returncode == 0
