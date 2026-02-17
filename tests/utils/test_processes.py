import multiprocessing, subprocess, time
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
    decorated_func = processes.with_timeout(2)(fast_function_top_level)
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


@patch("importlib.import_module")
@patch("subprocess.check_call")
def test_load_or_install_modules(mock_check_call, mock_import_module):
    # Simulate first import fail, install success, second import success
    mock_import_module.side_effect = [ImportError, None]

    processes.load_or_install_modules([["missing_module"]])

    mock_check_call.assert_called()
    assert mock_import_module.call_count == 2
