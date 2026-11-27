import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys

import pytest

from library import completions
from library.__main__ import library as lb


@pytest.mark.parametrize("shell", completions.available_shells())
def test_completion_scripts_include_nested_commands_and_legacy_aliases(shell):
    script = completions.generate(shell)

    assert "database add filesystem" in script
    assert "fs-add" in script
    assert "--media-type" in script
    assert "lb" in script


@pytest.mark.parametrize("shell", completions.available_shells())
def test_completion_scripts_include_shell_specific_entrypoints(shell):
    script = completions.generate(shell)

    if shell == "zsh":
        assert script.startswith("#compdef lb library")
    elif shell == "fish":
        assert "complete -c lb" in script
    elif shell == "bash":
        assert "complete -o default -F _lb_complete lb library" in script
    else:
        assert "Register-ArgumentCompleter -Native -CommandName lb,library" in script


def test_completion_commands_include_parser_options_and_choices():
    commands = completions.completion_commands()
    command = commands["database", "add", "filesystem"]

    assert command.target == "fs-add"
    assert "--ext" in command.options
    assert command.value_choices["--media-type"] == (
        "auto",
        "video",
        "audio",
        "image",
        "text",
        "filesystem",
    )


def test_completion_commands_include_positional_choices():
    command = completions.completion_commands()["completions",]

    assert command.positional_choices == completions.available_shells()


def test_completions_command_lists_supported_shells(capsys):
    lb(["completions", "--list"])

    assert capsys.readouterr().out.splitlines() == list(completions.available_shells())


def test_completions_command_prints_script(capsys):
    lb(["completions", "bash"])

    output = capsys.readouterr().out
    assert output.startswith("# bash completion for library / lb")


def test_completions_command_defaults_to_shell_list(capsys):
    lb(["completions"])

    assert capsys.readouterr().out.splitlines() == list(completions.available_shells())


def test_bash_completion_script_has_valid_syntax(tmp_path):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not installed")

    script = tmp_path / "lb.bash"
    script.write_text(completions.generate("bash"), encoding="utf-8")

    subprocess.run([bash, "-n", str(script)], check=True)


def test_fish_completion_script_has_valid_syntax(tmp_path):
    fish = shutil.which("fish")
    if fish is None:
        pytest.skip("fish not installed")

    script = tmp_path / "lb.fish"
    script.write_text(completions.generate("fish"), encoding="utf-8")

    subprocess.run([fish, "--no-execute", str(script)], check=True)


def test_generated_completion_paths_are_unambiguous():
    root = completions._completion_root()  # ruff: ignore[private-member-access]
    paths = {}

    for node in completions._ordered_nodes(root):  # ruff: ignore[private-member-access]
        for pattern in completions._node_patterns(node):  # ruff: ignore[private-member-access]
            assert pattern not in paths, f"{pattern!r} is used by {paths.get(pattern)!r} and {node.path!r}"
            paths[pattern] = node.path


def test_completion_scripts_are_reproducible():
    for shell in completions.available_shells():
        assert completions.generate(shell) == completions.generate(shell)


def test_completion_scripts_do_not_require_python_at_completion_time():
    for shell in completions.available_shells():
        script = completions.generate(shell)
        assert "subprocess" not in script
        assert sys.executable not in script


def test_install_bash_writes_completion_files(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    paths = completions.install("bash")

    assert [path.name for path in paths] == ["lb", "library"]
    assert paths[0] == tmp_path / "data" / "bash-completion" / "completions" / "lb"
    assert "complete -o default -F _lb_complete" in paths[0].read_text(encoding="utf-8")
    assert "source" in paths[1].read_text(encoding="utf-8")


def test_install_fish_writes_completion_files(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    paths = completions.install("fish")

    assert [path.name for path in paths] == ["lb.fish", "library.fish"]
    assert paths[0] == tmp_path / "config" / "fish" / "completions" / "lb.fish"
    assert "complete -c lb" in paths[0].read_text(encoding="utf-8")


def test_install_zsh_writes_completion_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    paths = completions.install("zsh")

    assert [path.name for path in paths] == ["_lb", "_library"]
    assert paths[0] == tmp_path / "data" / "zsh" / "site-functions" / "_lb"
    assert paths[0].read_text(encoding="utf-8").startswith("#compdef lb library")


def test_install_powershell_writes_completion_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))

    paths = completions.install("powershell")

    if os.name == "nt":
        completion_dir = tmp_path / "home" / "Documents" / "PowerShell" / "completions"
    else:
        completion_dir = tmp_path / "config" / "powershell" / "completions"

    assert [path.name for path in paths] == ["lb.ps1"]
    assert paths[0] == completion_dir / "lb.ps1"
    assert "Register-ArgumentCompleter" in paths[0].read_text(encoding="utf-8")


def test_install_refuses_to_overwrite_foreign_files_without_force(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    lb_path = tmp_path / "data" / "bash-completion" / "completions" / "lb"
    lb_path.parent.mkdir(parents=True)
    lb_path.write_text("custom completion\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        completions.install("bash")

    assert lb_path.read_text(encoding="utf-8") == "custom completion\n"

    completions.install("bash", force=True)
    assert "Generated by `library completions" in lb_path.read_text(encoding="utf-8")


def test_uninstall_removes_generated_files(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    paths = completions.install("fish")

    removed = completions.uninstall("fish")

    assert removed == paths
    assert all(not path.exists() for path in paths)


def test_uninstall_refuses_to_remove_foreign_files_without_force(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    foreign = tmp_path / "config" / "fish" / "completions" / "lb.fish"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("custom completion\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to remove"):
        completions.uninstall("fish")

    assert foreign.read_text(encoding="utf-8") == "custom completion\n"

    completions.uninstall("fish", force=True)
    assert not foreign.exists()


def test_detect_shell_reads_shell_environment(monkeypatch):
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setenv("SHELL", "/usr/bin/fish")

    assert completions.detect_shell() == "fish"


def test_detect_shell_recognizes_powershell_module_path(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setenv("PSModulePath", "/opt/microsoft/powershell/Modules")

    assert completions.detect_shell() == "powershell"


def test_completions_command_installs_for_requested_shell(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    lb(["completions", "--install", "fish"])

    output = capsys.readouterr().out
    assert "Installed fish completions:" in output
    assert "Completions load automatically" in output
    assert (tmp_path / "config" / "fish" / "completions" / "lb.fish").is_file()


def test_completions_command_installs_for_detected_shell(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    lb(["completions", "--install"])

    output = capsys.readouterr().out
    assert "Installed bash completions:" in output
    assert (tmp_path / "data" / "bash-completion" / "completions" / "lb").is_file()


def test_completions_command_uninstalls_for_requested_shell(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    completions.install("fish")

    lb(["completions", "--uninstall", "fish"])

    output = capsys.readouterr().out
    assert "Removed fish completions:" in output
    assert not (tmp_path / "config" / "fish" / "completions" / "lb.fish").exists()


def test_completions_command_rejects_multiple_shells_without_install():
    with pytest.raises(SystemExit):
        lb(["completions", "bash", "fish"])


def test_completions_command_requires_detectable_shell_for_install(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)

    with pytest.raises(SystemExit):
        lb(["completions", "--install"])
