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
