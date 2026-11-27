"""Generate shell completion scripts for the ``library`` CLI.

The completion scripts are generated from the same command registry and argparse
parsers that the CLI itself uses, so nested commands, aliases, options, and
``choices`` values stay in sync with the executable.

Examples
--------
>>> "bash" in available_shells()
True
>>> "database add filesystem" in generate("fish")
True

Generate completion files for the shells that ship with the repository::

    library completions bash > completions/lb.bash
    library completions zsh > completions/_lb
    library completions fish > completions/lb.fish
    library completions powershell > completions/lb.ps1

"""

from __future__ import annotations

import contextlib
import copy
import itertools
import shlex
from dataclasses import dataclass, field
from functools import cache, lru_cache
from typing import TYPE_CHECKING

from library import __main__ as cli
from library.utils import argparse_utils

if TYPE_CHECKING:
    import argparse
    from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence

SHELLS = ("bash", "zsh", "fish", "powershell")
PARSE_METHODS = (
    "parse_args",
    "parse_known_args",
    "parse_intermixed_args",
    "parse_known_intermixed_args",
)
COMMAND_HELP_OPTIONS = ("--help", "-h")
ROOT_OPTIONS = ("--help", "-h", "--version", "-V")
MIN_LEGACY_ALIAS_LENGTH = 2

USAGE = {
    "completions": """library completions [SHELL] [--list]

    Print a completion script for SHELL. Supported shells: bash, zsh, fish,
    powershell. Without SHELL, --list prints the supported shells.

    Install the generated script with your shell's normal completion
    mechanism. For example:

        library completions bash > ~/.local/share/bash-completion/completions/lb
        library completions zsh > "${fpath[1]}/_lb"
        library completions fish > ~/.config/fish/completions/lb.fish

    The repository also contains ready-to-install files in completions/.
""",
}


@dataclass(frozen=True)
class CompletionCommand:
    """Completion metadata for one executable command path.

    Examples
    --------
    >>> completion_commands()[("database", "add", "filesystem")].target
    'fs-add'

    """

    path: tuple[str, ...]
    target: str
    description: str
    options: tuple[str, ...]
    value_choices: Mapping[str, tuple[str, ...]]


@dataclass
class _Node:
    name: str
    path: tuple[str, ...]
    target: str | None = None
    description: str = ""
    children: dict[str, _Node] = field(default_factory=dict)
    aliases: set[str] = field(default_factory=set)
    flat_aliases: set[str] = field(default_factory=set)
    options: tuple[str, ...] = ()
    value_choices: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def is_leaf(self) -> bool:
        return not self.children


class _ParserCapturedError(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__("parser captured")
        self.parser = parser


@contextlib.contextmanager
def _capture_parse_calls() -> Generator[None]:
    originals = {name: getattr(argparse_utils.ArgumentParser, name) for name in PARSE_METHODS}

    def capture(parser: argparse.ArgumentParser, *_args, **_kwargs) -> None:
        raise _ParserCapturedError(parser)

    for name in PARSE_METHODS:
        setattr(argparse_utils.ArgumentParser, name, capture)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(argparse_utils.ArgumentParser, name, original)


def _capture_parser(target: str) -> argparse.ArgumentParser | None:
    """Build a command's parser without parsing argv or running the command.

    Returns
    -------
    argparse.ArgumentParser | None
        The command's parser, or None when the command could not be imported.

    Examples
    --------
    >>> parser = _capture_parser("fs-add")
    >>> parser is None
    False

    """
    try:
        with _capture_parse_calls():
            cli._invoke_target(target)  # ruff: ignore[private-member-access]
    except _ParserCapturedError as captured:
        return captured.parser
    except (Exception, SystemExit):
        # Optional dependency missing or an unusual command constructs its
        # parser outside of parse_args(). Command names still complete without
        # per-command options.
        return None
    return None


@cache
def _parser_metadata(target: str) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    parser = _capture_parser(target)
    if parser is None:
        return COMMAND_HELP_OPTIONS, {}

    options: list[str] = []
    value_choices: dict[str, tuple[str, ...]] = {}
    for action in parser._actions:  # ruff: ignore[private-member-access]
        for option in action.option_strings:
            if option not in options:
                options.append(option)

        choices = getattr(action, "choices", None)
        if choices:
            values = tuple(str(choice) for choice in choices)
            if values and all(" " not in value for value in values):
                for option in action.option_strings:
                    value_choices[option] = values

    for option in COMMAND_HELP_OPTIONS:
        if option not in options:
            options.append(option)

    return tuple(options), value_choices


def _invert_aliases(aliases: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    inverted: dict[str, list[str]] = {}
    for alias, canonical in aliases.items():
        inverted.setdefault(canonical, []).append(alias)
    return {canonical: tuple(names) for canonical, names in inverted.items()}


def _command_descriptions() -> dict[tuple[str, ...], str]:
    descriptions = {}
    for _category, commands in cli.command_catalog():
        for path, description in commands:
            descriptions[tuple(path.split())] = description
    return descriptions


def _build_node(name: str, data, path: tuple[str, ...], descriptions: Mapping[tuple[str, ...], str]) -> _Node:
    node = _Node(name=name, path=path, description=descriptions.get(path, ""))
    if isinstance(data, str):
        node.target = data
        return node

    node.target = data.get("_target")
    for child_name, child_data in data.items():
        if child_name == "_target":
            continue
        node.children[child_name] = _build_node(child_name, child_data, (*path, child_name), descriptions)
    return node


def _find_node(root: _Node, path: Sequence[str]) -> _Node | None:
    node = root
    for part in path:
        node = node.children.get(part)
        if node is None:
            return None
    return node


def _annotate(node: _Node) -> None:
    if node.target:
        options, value_choices = _parser_metadata(node.target)
        node.options = options
        node.value_choices = value_choices
    for child in node.children.values():
        _annotate(child)


def _add_path_aliases(root: _Node, group_aliases: Mapping[str, tuple[str, ...]]) -> None:
    for alias_path, target_path in cli.NESTED_PATH_ALIASES.items():
        target_node = _find_node(root, target_path)
        if target_node is None:
            continue

        parent = root
        for part in alias_path[:-1]:
            parent = parent.children.get(part)
            if parent is None:
                break
        else:
            alias_node = copy.copy(target_node)
            alias_node.name = alias_path[-1]
            alias_node.path = tuple(alias_path)
            alias_node.aliases = set(group_aliases.get(alias_path[-1], ()))
            # Legacy flat aliases belong to the canonical path, not to every
            # alternate nested route that points at the same target.
            alias_node.flat_aliases = set()
            parent.children[alias_path[-1]] = alias_node


def _add_flat_aliases(root: _Node) -> None:
    canonical_paths = cli.canonical_target_paths()
    group_names = set(cli.NESTED_COMMANDS) | set(cli.NESTED_GROUP_ALIASES)
    aliases = dict(cli.module_alias_targets())
    aliases.update({target: target for target in canonical_paths})
    for alias, target in aliases.items():
        if len(alias) < MIN_LEGACY_ALIAS_LENGTH or alias in group_names:
            continue
        canonical_path = canonical_paths.get(target)
        if canonical_path is None:
            continue
        node = _find_node(root, canonical_path.split())
        if node is not None and node.target:
            node.flat_aliases.add(alias)


@lru_cache(maxsize=1)
def _completion_root() -> _Node:
    descriptions = _command_descriptions()
    group_aliases = _invert_aliases(cli.NESTED_GROUP_ALIASES)
    command_aliases = _invert_aliases(cli.NESTED_COMMAND_ALIASES)

    root = _Node(name="", path=())
    for group, data in cli.NESTED_COMMANDS.items():
        node = _build_node(group, data, (group,), descriptions)
        node.aliases = set(group_aliases.get(group, ()))
        root.children[group] = node

    for path, node in _iter_nodes(root):
        if len(path) > 1:
            node.aliases = set(command_aliases.get(node.name, ()))

    _add_path_aliases(root, group_aliases)
    _annotate(root)
    _add_flat_aliases(root)
    return root


def _iter_nodes(node: _Node) -> Iterator[tuple[tuple[str, ...], _Node]]:
    yield node.path, node
    for child in node.children.values():
        yield from _iter_nodes(child)


@lru_cache(maxsize=1)
def completion_commands() -> dict[tuple[str, ...], CompletionCommand]:
    """Return completion metadata keyed by canonical command path.

    Returns
    -------
    dict[tuple[str, ...], CompletionCommand]
        Completion metadata for each executable canonical command path.

    Examples
    --------
    >>> completion_commands()[("completions",)].target
    'completions'

    """
    commands = {}
    for path, node in _iter_nodes(_completion_root()):
        if node.target and path:
            commands[path] = CompletionCommand(
                path=path,
                target=node.target,
                description=node.description,
                options=node.options,
                value_choices=dict(node.value_choices),
            )
    return commands


def _group_aliases() -> dict[str, tuple[str, ...]]:
    return _invert_aliases(cli.NESTED_GROUP_ALIASES)


def _command_aliases() -> dict[str, tuple[str, ...]]:
    return _invert_aliases(cli.NESTED_COMMAND_ALIASES)


def _path_variants(node: _Node) -> list[tuple[str, ...]]:
    group_aliases = _group_aliases()
    command_aliases = _command_aliases()
    segment_options = []
    for index, part in enumerate(node.path):
        aliases = group_aliases.get(part, ()) if index == 0 else command_aliases.get(part, ())
        segment_options.append([part, *aliases])

    variants = list(itertools.product(*segment_options)) if segment_options else []
    variants.extend((alias,) for alias in sorted(node.flat_aliases))
    return list(dict.fromkeys(variants))


def _subcommand_candidates(node: _Node) -> list[tuple[str, str]]:
    candidates: dict[str, str] = {}
    for child in node.children.values():
        candidates.setdefault(child.name, child.description or f"{child.name} command")
        for alias in sorted(child.aliases):
            candidates.setdefault(alias, f"Alias for {child.name}")

    for alias in sorted(node.flat_aliases):
        candidates.setdefault(alias, node.description or "Alias for another command")
    return list(candidates.items())


def _root_candidates(root: _Node) -> list[tuple[str, str]]:
    candidates = _subcommand_candidates(root)
    known = {name for name, _description in candidates}
    for option in ROOT_OPTIONS:
        if option not in known:
            description = "Show help" if option in {"--help", "-h"} else "Show version"
            candidates.append((option, description))
    return candidates


def _node_value_choices(node: _Node) -> dict[str, tuple[str, ...]]:
    return node.value_choices


def _ordered_nodes(root: _Node) -> list[_Node]:
    nodes = [node for _path, node in _iter_nodes(root)]
    nodes.sort(key=lambda node: (-len(node.path), node.path))
    return nodes


def _node_patterns(node: _Node) -> list[str]:
    if not node.path:
        return [""]
    return [" ".join(variant) for variant in _path_variants(node)]


def _bash_quote(text: str) -> str:
    return shlex.quote(text)


def _bash_compgen(candidates: str) -> str:
    return f'COMPREPLY=($(compgen -W {_bash_quote(candidates)} -- "$cur"))'


def bash_script() -> str:
    root = _completion_root()
    lines = [
        "# bash completion for library / lb",
        "# Generated by `library completions bash`.",
        "# Install: source this file or copy it to a bash-completion directory as `lb`.",
        "",
        "_lb_complete() {",
        '    local cur prev path word',
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        '    prev="${COMP_WORDS[COMP_CWORD-1]}"',
        '    path=""',
        "    local i word",
        "    for ((i = 1; i < COMP_CWORD; i++)); do",
        '        word="${COMP_WORDS[i]}"',
        '        if [[ "$word" == -* ]]; then',
        "            break",
        "        fi",
        '        path+="$word "',
        "    done",
        '    path="${path% }"',
        "",
        '    case "$path" in',
    ]

    seen_patterns: set[str] = set()
    for node in _ordered_nodes(root):
        patterns = [pattern for pattern in _node_patterns(node) if pattern not in seen_patterns]
        seen_patterns.update(patterns)
        if not patterns:
            continue

        lines.append("        " + "|".join(_bash_quote(pattern) for pattern in patterns) + ")")
        value_choices = _node_value_choices(node)
        if value_choices:
            lines.append('            case "$prev" in')
            for option, values in sorted(value_choices.items()):
                lines.extend(
                    [
                        f"                {_bash_quote(option)})",
                        "                    " + _bash_compgen(" ".join(values)),
                        "                    return 0",
                        "                    ;;",
                    ]
                )
            lines.append("            esac")

        if node is root:
            candidates = " ".join(name for name, _description in _root_candidates(root))
            lines.extend(["            " + _bash_compgen(candidates), "            return 0"])
        elif node.children:
            if node.options:
                lines.extend(
                    [
                        '            if [[ "$cur" == -* ]]; then',
                        "                " + _bash_compgen(" ".join(node.options)),
                        "                return 0",
                        "            fi",
                    ]
                )
            candidates = " ".join(name for name, _description in _subcommand_candidates(node))
            lines.extend(["            " + _bash_compgen(candidates), "            return 0"])
        else:
            if node.options:
                lines.extend(
                    [
                        '            if [[ "$cur" == -* ]]; then',
                        "                " + _bash_compgen(" ".join(node.options)),
                        "                return 0",
                        "            fi",
                    ]
                )
            lines.extend(
                [
                    "            compopt -o default 2>/dev/null || true",
                    "            COMPREPLY=()",
                    "            return 0",
                ]
            )
        lines.append("            ;;")

    lines.extend(
        [
            "    esac",
            "}",
            "",
            "complete -o default -F _lb_complete lb library",
            "",
        ]
    )
    return "\n".join(lines)


def _zsh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _zsh_describe(value: str, description: str) -> str:
    description = description.replace("\n", " ").replace(":", " -")
    return _zsh_quote(f"{value}:{description}")


def zsh_script() -> str:
    root = _completion_root()
    lines = [
        "#compdef lb library",
        "# zsh completion for library / lb.",
        "# Generated by `library completions zsh`.",
        "",
        "_lb() {",
        "    local cur prev path word",
        "    local -a path_words",
        "    cur=${words[CURRENT]}",
        "    prev=${words[CURRENT-1]}",
        "    for word in ${words[2,CURRENT-1]}; do",
        '        if [[ $word == -* ]]; then',
        "            break",
        "        fi",
        "        path_words+=($word)",
        "    done",
        "    path=${(j: :)path_words}",
        "",
        "    case $path in",
    ]

    seen_patterns: set[str] = set()
    for node in _ordered_nodes(root):
        patterns = [pattern for pattern in _node_patterns(node) if pattern not in seen_patterns]
        seen_patterns.update(patterns)
        if not patterns:
            continue

        lines.append("        " + "|".join(_zsh_quote(pattern) for pattern in patterns) + ")")
        value_choices = _node_value_choices(node)
        if value_choices:
            lines.append("            case $prev in")
            for option, values in sorted(value_choices.items()):
                lines.extend(
                    [
                        "                " + _zsh_quote(option) + ")",
                        "                    compadd -- " + " ".join(_zsh_quote(value) for value in values),
                        "                    return",
                        "                    ;;",
                    ]
                )
            lines.append("            esac")

        if node is root:
            lines.append("            local -a commands=(")
            lines.extend(
                "                " + _zsh_describe(name, description)
                for name, description in _root_candidates(root)
            )
            lines.extend(
                [
                    "            )",
                    "            _describe -t commands 'library command' commands",
                    "            return",
                ]
            )
        elif node.children:
            if node.options:
                lines.extend(
                    [
                        '            if [[ $cur == -* ]]; then',
                        "                compadd -- " + " ".join(_zsh_quote(option) for option in node.options),
                        "                return",
                        "            fi",
                    ]
                )
            lines.append("            local -a commands=(")
            lines.extend(
                "                " + _zsh_describe(name, description)
                for name, description in _subcommand_candidates(node)
            )
            lines.extend(
                [
                    "            )",
                    "            _describe -t commands 'command' commands",
                    "            return",
                ]
            )
        else:
            if node.options:
                lines.extend(
                    [
                        '            if [[ $cur == -* ]]; then',
                        "                compadd -- " + " ".join(_zsh_quote(option) for option in node.options),
                        "                return",
                        "            fi",
                    ]
                )
            lines.extend(["            _files", "            return"])
        lines.append("            ;;")

    lines.extend(["    esac", "}", "", '_lb "$@"', ""])
    return "\n".join(lines)


def _fish_quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _fish_condition(path_patterns: Sequence[str]) -> str:
    if not path_patterns:
        return "false"
    paths = " ".join(_fish_quote(path) for path in path_patterns)
    return f"contains -- (__lb_path) {paths}"


def fish_script() -> str:
    root = _completion_root()
    lines = [
        "# fish completion for library / lb",
        "# Generated by `library completions fish`.",
        "# Install: copy to ~/.config/fish/completions/lb.fish (and library.fish).",
        "",
        "function __lb_path",
        "    set -l path",
        "    for token in (commandline -opc)[2..-1]",
        "        if string match -q -- '-*' $token",
        "            break",
        "        end",
        "        set -a path $token",
        "    end",
        "    string join ' ' -- $path",
        "end",
        "",
        "function __lb_prev",
        "    set -l tokens (commandline -opc)",
        "    if test (count $tokens) -gt 1",
        "        printf '%s\\n' $tokens[-1]",
        "    end",
        "end",
        "",
        "complete -c lb -f",
        "complete -c library -w lb",
        "",
    ]

    root_condition = "test (count (commandline -opc)) -eq 1"
    for name, description in _root_candidates(root):
        lines.append(
            "complete -c lb -n "
            + _fish_quote(root_condition)
            + " -a "
            + _fish_quote(name)
            + " -d "
            + _fish_quote(description)
        )

    seen_patterns: set[str] = set()
    for node in _ordered_nodes(root):
        if not node.path:
            continue
        patterns = [pattern for pattern in _node_patterns(node) if pattern not in seen_patterns]
        seen_patterns.update(patterns)
        if not patterns:
            continue

        condition = _fish_condition(patterns)
        for option, values in sorted(node.value_choices.items()):
            value_condition = (
                condition + "; and test (__lb_prev) = " + _fish_quote(option)
            )
            lines.append(
                "complete -c lb -n "
                + _fish_quote(value_condition)
                + " -a "
                + _fish_quote(" ".join(values))
            )

        option_condition = condition + "; and string match -q -- '-*' (commandline -ct)"
        if node.children:
            for name, description in _subcommand_candidates(node):
                lines.append(
                    "complete -c lb -n "
                    + _fish_quote(condition)
                    + " -a "
                    + _fish_quote(name)
                    + " -d "
                    + _fish_quote(description)
                )
            if node.options:
                lines.append(
                    "complete -c lb -n "
                    + _fish_quote(option_condition)
                    + " -a "
                    + _fish_quote(" ".join(node.options))
                )
        else:
            if node.options:
                lines.append(
                    "complete -c lb -n "
                    + _fish_quote(option_condition)
                    + " -a "
                    + _fish_quote(" ".join(node.options))
                )
            file_condition = condition + "; and not string match -q -- '-*' (commandline -ct)"
            if node.value_choices:
                choice_options = " ".join(_fish_quote(option) for option in sorted(node.value_choices))
                file_condition += "; and not contains -- (__lb_prev) " + choice_options
            lines.append("complete -c lb -n " + _fish_quote(file_condition) + " -F")

    lines.append("")
    return "\n".join(lines)


def _powershell_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _powershell_array(values: Iterable[str]) -> str:
    return "@(" + ", ".join(_powershell_quote(value) for value in values) + ")"


def _powershell_body(node: _Node, root: _Node) -> list[str]:
    lines = []
    if node.value_choices:
        lines.append("switch -Exact ($prev) {")
        for option, values in sorted(node.value_choices.items()):
            lines.append(f"    {_powershell_quote(option)} {{ New-Completion {_powershell_array(values)}; return }}")
        lines.append("}")

    if node is root:
        lines.append(f"New-Completion {_powershell_array(name for name, _description in _root_candidates(root))}")
    elif node.children:
        if node.options:
            lines.append(f"if ($wordToComplete -like '-*') {{ New-Completion {_powershell_array(node.options)}; return }}")
        lines.append(
            f"New-Completion {_powershell_array(name for name, _description in _subcommand_candidates(node))}"
        )
    else:
        if node.options:
            lines.append(f"if ($wordToComplete -like '-*') {{ New-Completion {_powershell_array(node.options)}; return }}")
        lines.append("New-FileCompletion")
    return lines


def powershell_script() -> str:
    root = _completion_root()
    lines = [
        "# PowerShell completion for library / lb",
        "# Generated by `library completions powershell`.",
        "# Install: add `. /path/to/lb.ps1` to your PowerShell profile.",
        "",
        "using namespace System.Management.Automation",
        "",
        "Register-ArgumentCompleter -Native -CommandName lb,library -ScriptBlock {",
        "    param($wordToComplete, $commandAst, $cursorPosition)",
        "",
        "    $words = @()",
        "    for ($i = 1; $i -lt $commandAst.CommandElements.Count; $i++) {",
        "        $element = $commandAst.CommandElements[$i]",
        "        if ($element.Extent.EndOffset -lt $cursorPosition) {",
        "            $words += $element.Extent.Text",
        "        }",
        "    }",
        "    $pathWords = @()",
        "    foreach ($word in $words) {",
        "        if ($word -like '-*') { break }",
        "        $pathWords += $word",
        "    }",
        "    $path = $pathWords -join ' '",
        "    $prev = if ($words.Count -gt 0) { $words[-1] } else { '' }",
        "",
        "    function New-Completion([string[]]$values) {",
        '        $values | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {',
        "            [CompletionResult]::new($_, $_, [CompletionResultType]::ParameterValue, $_)",
        "        }",
        "    }",
        "",
        "    function New-FileCompletion {",
        '        Get-ChildItem -Path "$wordToComplete*" -ErrorAction SilentlyContinue | ForEach-Object {',
        "            [CompletionResult]::new($_.Name, $_.Name, [CompletionResultType]::ProviderItem, $_.FullName)",
        "        }",
        "    }",
        "",
        "    $canonicalPath = switch -Exact ($path) {",
    ]

    nodes = _ordered_nodes(root)
    for node in nodes:
        canonical = " ".join(node.path)
        lines.extend(
            f"        {_powershell_quote(pattern)} {{ {_powershell_quote(canonical)}; break }}"
            for pattern in _node_patterns(node)
        )

    lines.extend(["    }", "", "    switch -Exact ($canonicalPath) {"])
    for node in nodes:
        canonical = " ".join(node.path)
        body = _powershell_body(node, root)
        lines.append("        " + _powershell_quote(canonical) + " {")
        lines.extend("            " + line for line in body)
        lines.append("        }")

    lines.extend(["    }", "}", ""])
    return "\n".join(lines)


_GENERATORS = {
    "bash": bash_script,
    "zsh": zsh_script,
    "fish": fish_script,
    "powershell": powershell_script,
}


def available_shells() -> tuple[str, ...]:
    """Return the shell names accepted by :func:`generate`.

    Returns
    -------
    tuple[str, ...]
        Supported shell names.

    Examples
    --------
    >>> available_shells()
    ('bash', 'zsh', 'fish', 'powershell')

    """
    return SHELLS


def generate(shell: str) -> str:
    """Return a completion script for ``shell``.

    Returns
    -------
    str
        The completion script.

    Raises
    ------
    ValueError
        If ``shell`` is not one of :func:`available_shells`.

    Examples
    --------
    >>> generate("bash").startswith("# bash completion")
    True

    """
    try:
        generator = _GENERATORS[shell.lower()]
    except KeyError as exc:
        message = f"Unsupported shell: {shell}. Choose from: {', '.join(SHELLS)}"
        raise ValueError(message) from exc
    return generator()


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=USAGE["completions"])
    parser.add_argument("shell", nargs="?", choices=SHELLS, help="Shell to generate completions for")
    parser.add_argument("--list", action="store_true", help="List supported shells")
    args = parser.parse_args()
    return args


def completions() -> None:
    args = parse_args()
    if args.list or not args.shell:
        print("\n".join(available_shells()))
        return
    try:
        print(generate(args.shell))
    except BrokenPipeError:
        # `library completions bash | head` is a normal way to inspect output.
        return


if __name__ == "__main__":
    completions()
