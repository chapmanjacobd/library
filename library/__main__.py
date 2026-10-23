import argparse, difflib, importlib, os, re, sys, textwrap

from tabulate import tabulate

from library._version import __version__
from library.utils import argparse_utils
from library.utils.log_utils import log

from library.command_registry import COMMANDS

MIN_CANONICAL_PATH_PARTS = 3
MIN_NESTED_ARGV_LENGTH = 2


progs = {
    "Media collection subcommands": {
        "database add filesystem": "Add local media",
        "database add video": "Add online video media (yt-dlp)",
        "database add gallery": "Add online gallery media (gallery-dl)",
        "database add open-directory": "Discover media in HTTP directory listings and folder-like web indexes",
        "database add reddit": "Create a reddit database; Add subreddits",
        "database add hackernews": "Create / Update a Hacker News database",
        "database add getty": "Create / Update a Getty Museum database",
        "database add substack": "Backup substack articles",
        "database add tildes": "Backup tildes comments and topics",
    },
    "Playback subcommands": {
        "play media": "Play media of any supported type",
        "play video": "Watch / Listen",
        "play audio": "Listen to audio",
        "play text": "Read text",
        "play images": "View images",
        "playback now": "Show what is currently playing",
        "playback next": "Play next file and optionally delete current file",
        "playback seek": "Set playback to a certain time, fast-forward or rewind",
        "playback stop": "Stop all playback",
        "playback pause": "Pause all playback",
    },
    "Web collection subcommands": {
        "database add links": "Extract links from webpages, paginated lists, recursive sites, and web archives",
        "links open": "Open links from link dbs",
        "links extract": "Extract inner links from lists of web links",
        "links download": "Download links from lists of web links",
        "database add tabs": "Schedule URLs for recurring browser visits",
        "tabs open": "Open your tabs for the day",
        "tabs shuffle": "Randomize tabs.db a bit",
        "database add site": "Extract structured website data into SQLite",
    },
    "Download subcommands": {
        "download": "Download media",
        "database download": "Download media recorded in a database",
        "database download block": "Block a channel",
        "database download status": "Show download status",
        "database redownload": "Re-download deleted/lost media",
    },
    "Database management subcommands": {
        "database search": "Search a SQLite database",
        "database merge": "Merge SQLite databases",
        "database dedupe": "Dedupe SQLite tables",
    },
    "Media database management subcommands": {
        "captions": "Search captions / subtitles",
        "database playlists": "List stored playlists",
        "database history": "Show and manage playback history",
        "database history add": "Add history from paths",
        "database stats": "Show some event statistics (created, deleted, watched, etc)",
        "database stats words": "Aggregate media size by words in paths",
        "database stats schema": "Show SQLite table, column, index, and storage statistics",
        "database tail": "Watch a SQLite database for newly appended rows",
        "database copy play-counts": "Copy play history",
        "database dedupe media": "Dedupe similar media",
        "file dedupe czkawka": "Process czkawka diff output",
        "database merge online-local": "Merge online and local data",
        "database enrich reddit-selftext": "Copy selftext links to media table",
        "database enrich imdb": "Enrich media metadata from cached IMDb datasets",
        "database export html": "Export HTML files from SQLite databases",
        "database optimize": "Re-optimize database",
    },
    "File and folder subcommands": {
        "folder merge move": "Move files and merge folders in BSD/rsync style, rename if possible",
        "folder merge copy": "Copy files and merge folders",
        "folder merge relative-move": "Move files while preserving relative paths",
        "folder merge relative-copy": "Copy files while preserving relative paths",
        "folder copy mergerfs": "cp files with reflink on mergerfs",
        "folder move list": "Find specific folders to move to different disks",
        "folder large": "Show large folders",
        "folder scatter": "Scatter files between folders or disks",
        "folder similar": "Find similar folders based on folder name, size, and count",
        "folder organize": "Organize folders by their dominant file type",
        "file normalize": "Clean file paths",
        "file hash": "Calculate a hash based on small file segments",
        "file compare": "Compare files using sample-hash and other shortcuts",
        "file similar": "Find similar files based on filename, size, duration, or sampled content",
        "file case-conflicts": "Find and optionally merge case-folded path conflicts",
        "file media-hash": "Hash decoded audio/video streams with ffmpeg",
        "file media-compare": "Compare decoded audio/video streams",
    },
    "Filesystem inspection subcommands": {
        "filesystem list": "Find files by mimetype and size",
        "filesystem usage": "Show disk usage",
        "filesystem usage extensions": "Show disk usage grouped by file extension",
        "filesystem usage mimetypes": "Show disk usage grouped by MIME type",
        "filesystem usage sizes": "Show disk usage grouped by file size",
        "filesystem usage modified": "Show a modification-time histogram and outliers",
        "filesystem mounts stats": "Show some relative mount stats",
        "filesystem mounts free": "Show system-wide disk usage",
    },
    "Media processing subcommands": {
        "file check": "Check media via ffmpeg or raw filesystem I/O with --filesystem",
        "shrink media": "Estimate and execute potential disk space savings",
        "shrink table": "Convert table-like files to compressed Parquet",
        "shrink video": "Shrink video/audio to AV1/Opus format (.mkv, .mka)",
        "shrink audio": "Shrink audio to Opus",
        "shrink image": "Shrink images to AV1 image format (.avif)",
        "shrink text": "Shrink documents to HTML+AV1 image format (requires Calibre)",
        "archive extract": "Extract from archives and delete all associated multi-part archive files",
    },
    "Document processing subcommands": {
        "document convert": "Convert images, PDFs, and text-like documents to PDF",
        "document adjust pdf": "Apply brightness, contrast, saturation, and sharpness adjustments to PDFs",
        "document pdf header": "Stamp rendered Markdown/text onto PDF pages",
    },
    "Video extraction subcommands": {
        "video extract audio": "Extract audio streams without re-encoding",
        "video extract subtitles": "Extract embedded subtitle streams",
        "video extract scenes": "Extract scene changes as video, images, or contact sheets",
        "video extract keyframes": "Extract keyframes as video, images, slow-motion, or visually sorted video",
        "video detect": "Detect video properties",
    },
    "Video creation subcommands": {
        "video create slideshow": "Create a slideshow video, optionally with audio",
        "video concat": "Concatenate videos with stream copying",
    },
    "Text processing subcommands": {
        "text border": "Put text inside a simple border",
        "text clean": "Clean pasted text and preserve Markdown structure",
        "text group": "Group input lines by a regular expression",
        "text interleave": "Interleave lines from multiple inputs",
        "text markdown": "Convert simple HTML documents to Markdown",
        "text sort regex": "Sort text by regex split and corpus comparison",
        "text sort cluster": "Sort text by similarity",
        "text extract": "Extract human text from lists of web links",
        "text markdown links": "Extract titles from lists of web links",
        "text expand links": "Expand search urls with query text",
        "text combinations": "Enumerate possible combinations",
        "text nouns": "Unstructured text -> compound nouns (stdin)",
        "text timestamps": "Unstructured text -> timestamps",
        "text dates": "Unstructured text -> dates",
        "text times": "Unstructured text -> times",
    },
    "JSON processing subcommands": {
        "json rename-keys": "Rename JSON keys by substring match",
        "json remove-nulls": "Remove null values recursively from JSON",
    },
    "Image processing subcommands": {
        "image convert": "Convert images and comic archives into PDFs",
        "image sort cluster": "Sort images by similarity",
    },
    "Data import subcommands": {
        "database add tables": "Add table-like data to SQLite",
        "database add row": "Add arbitrary data to SQLite",
        "database import pushshift": "Convert pushshift data to reddit.db format (stdin)",
        "database import nicotine": "Import paths from nicotine+",
        "database import mpv-watchlater": "Import mpv watchlater files to history",
        "database import places": "Import places of interest (POIs)",
    },
    "Table analysis subcommands": {
        "table convert csv": "Convert JSON data to CSV",
        "table convert json": "Convert CSV data to JSON",
        "table analyze": "Exploratory Data Analysis on table-like files",
        "table rank": "Multi-criteria Ranking for Decision Support",
        "table plot": "Plot table-like files. A CLI interface to matplotlib",
        "table markdown": "Print markdown tables from table-like files",
        "table columns": "Print columns of table-like files",
        "table diff": "Diff large table-like files in chunks",
    },
    "Torrent subcommands": {
        "database add torrents": "Add torrent info to SQLite",
        "database add computers": "Add computer info to SQLite",
        "torrent allocate": "Use computers.db and torrents.db to allocate torrents",
        "torrent info": "List torrents (qBittorrent-nox)",
        "torrent start": "Start torrents (qBittorrent-nox)",
        "torrent remaining": "Overview of torrents by mountpoint (qBittorrent-nox)",
        "torrent dump": "Print torrent file info",
        "torrent match": "Match files on disk against torrent piece hashes",
        "torrent audit": "Find qBittorrent duplicate and orphan files",
    },
    "Database updating subcommands": {
        "database update filesystem": "Update local media",
        "database update video": "Update online video media",
        "database update web": "Update open-directory media",
        "database update gallery": "Update online gallery media",
        "database update reddit": "Update reddit media",
        "database update links": "Update a link-scraping database",
    },
    "Help subcommands": {
        "help search": "Search subcommands and help text",
    },
}


def _build_cli_metadata():
    modules = {record.module: list(record.aliases) for record in COMMANDS}
    path_records = [record for record in COMMANDS if record.path is not None]

    paths = {record.path for record in path_records}
    nested_commands = {}
    for record in path_records:
        parts = record.path.split()
        current = nested_commands
        for part in parts[:-1]:
            current = current.setdefault(part, {})

        leaf = parts[-1]
        has_children = any(other.startswith(f"{record.path} ") for other in paths)
        if has_children:
            current.setdefault(leaf, {})["_target"] = record.target
        else:
            current[leaf] = record.target

    return modules, nested_commands


modules, NESTED_COMMANDS = _build_cli_metadata()
NESTED_ONLY_MODULES = {
    "library.filesystem.filesystem.filesystem",
    "library.captions.search.search",
}


def usage() -> str:
    grouped_commands = command_catalog()

    tables = []
    for category, commands in grouped_commands:
        tables.append(f"\n    {category}:\n")
        table = tabulate(commands, tablefmt="rounded_grid", showindex=False)
        tables.append(textwrap.indent(table, "    "))
        tables.append("\n")

    count = len(_canonical_nested_paths_for_all_groups())
    return f"library (v{__version__}; {count} subcommands)\n{''.join(tables)}"


def print_help(parser) -> None:
    print(usage())
    print(parser.epilog)


NESTED_GROUP_ALIASES = {
    "db": "database",
    "doc": "document",
    "docs": "document",
    "fs": "filesystem",
    "files": "file",
}

NESTED_COMMAND_ALIASES = {
    "fs": "filesystem",
    "ls": "list",
    "explore": "analyze",
    "web": "open-directory",
}

NESTED_PATH_ALIASES = {
    ("video", "create", "images"): ("video", "create", "slideshow"),
    ("text", "convert"): ("document", "convert"),
}

for _group in NESTED_COMMANDS:
    _group_alias = _group.removesuffix("s") if _group.endswith("s") else f"{_group}s"
    NESTED_GROUP_ALIASES.setdefault(_group_alias, _group)


PREFERRED_NESTED_PATHS = {
    "filesystem": "filesystem list",
    "disk-usage": "filesystem usage",
    "extensions": "filesystem usage extensions",
    "mimetypes": "filesystem usage mimetypes",
    "sizes": "filesystem usage sizes",
}


def _canonical_nested_paths(
    group: str,
    command_tree,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    paths = []

    def walk(current, current_prefix: tuple[str, ...]) -> None:
        if isinstance(current, str):
            paths.append(" ".join((group, *current_prefix)))
            return

        if "_target" in current:
            paths.append(" ".join((group, *current_prefix)))
        for command, target in current.items():
            if command != "_target":
                walk(target, (*current_prefix, command))

    walk(command_tree, prefix)
    return paths


def _canonical_nested_paths_for_all_groups() -> list[str]:
    return [
        path
        for group, command_tree in NESTED_COMMANDS.items()
        for path in _canonical_nested_paths(group, command_tree)
    ]


def _expanded_aliases(module: str, aliases) -> list[str]:
    """Aliases plus the hyphen-less/underscore spellings argparse also accepts.

    Computed on demand instead of mutating the shared `modules` metadata.
    """
    name = module.rsplit(".", 1)[1].replace("_", "-")
    expanded = []
    for alias in (name, *aliases):
        if "-" in alias:
            expanded.append(alias.replace("-", ""))
            expanded.append(alias.replace("-", "_"))
    return [*aliases, *expanded]


def module_alias_targets() -> dict[str, str]:
    targets = {}
    for module, aliases in modules.items():
        target = module.rsplit(".", 1)[1].replace("_", "-")
        for alias in _expanded_aliases(module, aliases):
            targets.setdefault(alias, target)
    return targets


def _nested_target_canonical(path: list[str]) -> tuple[str, int] | None:
    if not path:
        return None

    group = path[0]
    command_tree = NESTED_COMMANDS.get(group)
    if isinstance(command_tree, str):
        return command_tree, 1
    if not isinstance(command_tree, dict):
        return None

    current = command_tree
    consumed = 1
    for part in path[1:]:
        if not isinstance(current, dict) or part not in current:
            break
        current = current[part]
        consumed += 1
        if isinstance(current, str):
            return current, consumed

    if isinstance(current, dict) and "_target" in current:
        return current["_target"], consumed
    return None


def _canonical_nested_path(path: list[str]) -> tuple[str, ...]:
    if not path:
        return ()
    canonical_path = (
        NESTED_GROUP_ALIASES.get(path[0], path[0]),
        *[NESTED_COMMAND_ALIASES.get(part, part) for part in path[1:]],
    )
    for alias, target in NESTED_PATH_ALIASES.items():
        if canonical_path[: len(alias)] == alias:
            return (*target, *canonical_path[len(alias) :])
    return canonical_path


def nested_target(path: list[str]) -> tuple[str, int] | None:
    if not path:
        return None

    canonical_path = _canonical_nested_path(path)
    target = _nested_target_canonical(list(canonical_path))
    if target is not None:
        return target

    # Also accept compact spellings such as `db fs update` for `database update filesystem`
    # (the resource and the operation swapped), regardless of which group alias was used.
    if len(canonical_path) >= MIN_CANONICAL_PATH_PARTS:
        return _nested_target_canonical(
            [canonical_path[0], canonical_path[2], canonical_path[1], *canonical_path[3:]]
        )
    return None


def _nested_group(path: list[str]) -> str | None:
    """Return the canonical resource group for a token, including aliases.

    Group names and their aliases always win over same-named flat commands so that
    invalid subcommands get the helpful `Unknown command` diagnostic instead of a
    generic top-level `Subcommand not found` error.
    """
    if not path:
        return None

    group = NESTED_GROUP_ALIASES.get(path[0], path[0])
    if group not in NESTED_COMMANDS:
        return None
    return group


def _invalid_nested_path(group: str, path: list[str]) -> list[str] | None:
    command_tree = NESTED_COMMANDS.get(group)
    if not isinstance(command_tree, dict) or not path:
        return None

    canonical_path = _canonical_nested_path([group, *path[1:]])
    current = command_tree
    for index, part in enumerate(canonical_path[1:], start=1):
        if part in {"-h", "--help"}:
            return None
        if not isinstance(current, dict) or part not in current:
            return list(canonical_path[: index + 1])
        current = current[part]
        if isinstance(current, str):
            return None
    return None


def _nested_tree_node(path: list[str]) -> tuple[tuple[str, ...], object] | None:
    if not path:
        return None

    group = NESTED_GROUP_ALIASES.get(path[0], path[0])
    command_tree = NESTED_COMMANDS.get(group)
    if command_tree is None:
        return None

    canonical_path = _canonical_nested_path([group, *path[1:]])
    current = command_tree
    prefix = []
    for part in canonical_path[1:]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
        prefix.append(part)
    return tuple(prefix), current


def _nested_help(
    group: str,
    invalid_path: list[str] | None = None,
    prefix: tuple[str, ...] = (),
) -> str:
    command_tree = NESTED_COMMANDS[group]
    if isinstance(command_tree, str):
        return f"usage: library {group} DATABASE [optional args]"

    current = command_tree
    for part in prefix:
        if not isinstance(current, dict):
            return f"usage: library {group} <command> [optional args]"
        current = current[part]

    command_name = " ".join((group, *prefix))
    lines = [f"usage: library {command_name} <command> [optional args]", "", "Commands:"]
    prefix_text = f"{command_name} "
    lines.extend(
        f"  {path.removeprefix(prefix_text)}"
        for path in _canonical_nested_paths(group, current, prefix)
    )
    if invalid_path:
        relative = " ".join(invalid_path[1:])
        choices = [
            path.removeprefix(prefix_text)
            for path in _canonical_nested_paths(group, current, prefix)
        ]
        suggestion = difflib.get_close_matches(relative, choices, n=1, cutoff=0.4)
        message = [f"Unknown command: {' '.join(invalid_path)}"]
        if suggestion:
            message.append(f"Did you mean: {command_name} {suggestion[0]}?")
        lines = [*message, "", *lines]
    return "\n".join(lines)


def canonical_target_paths() -> dict[str, str]:
    target_paths = {}
    for path in _canonical_nested_paths_for_all_groups():
        target = nested_target(path.split())
        if target is not None:
            target_paths.setdefault(target[0], path)
    target_paths.update(
        {
            target: path
            for target, path in PREFERRED_NESTED_PATHS.items()
            if nested_target(path.split()) == (target, len(path.split()))
        }
    )
    return target_paths


def command_catalog() -> list[tuple[str, list[tuple[str, str]]]]:
    grouped_commands = []
    canonical_paths = set(_canonical_nested_paths_for_all_groups())
    target_paths = canonical_target_paths()
    seen = set()

    for category, category_progs in progs.items():
        commands = []
        for path, description in category_progs.items():
            path_parts = path.split()
            nested_target_info = nested_target(path_parts)
            canonical_path = (
                target_paths.get(nested_target_info[0])
                if nested_target_info is not None and nested_target_info[1] == len(path_parts)
                else None
            )
            if canonical_path not in canonical_paths:
                message = f"Unknown canonical command path in {category}: {path}"
                raise ValueError(message)
            if canonical_path in seen:
                message = f"Duplicate canonical command path in {category}: {path}"
                raise ValueError(message)
            seen.add(canonical_path)
            commands.append((canonical_path, description))
        if commands:
            grouped_commands.append((category, commands))

    missing_paths = canonical_paths - seen
    if missing_paths:
        missing = ", ".join(sorted(missing_paths))
        message = f"Canonical command paths are not categorized: {missing}"
        raise ValueError(message)

    return grouped_commands


def _module_canonical_paths() -> dict[str, str]:
    """Map each implementation module to the canonical nested path that calls it.

    This is the inverse of `_target_module`: it resolves aliases (eg. `mv-list` /
    `relmv`) so every legacy spelling of a command can be rewritten to its v4 path.
    """
    paths = {}
    for target, path in canonical_target_paths().items():
        try:
            module_name, function_name = _target_module(target)
        except KeyError:
            continue
        paths.setdefault(f"{module_name}.{function_name}", path)
    return paths


def _legacy_command_paths() -> dict[str, str]:
    canonical_paths = _module_canonical_paths()
    target_paths = canonical_target_paths()
    legacy_paths = {}
    for module, aliases in modules.items():
        canonical_path = canonical_paths.get(module)
        if canonical_path is None:
            continue

        function_name = module.rsplit(".", 1)[1]
        legacy_names = {
            function_name,
            function_name.replace("_", "-"),
            function_name.replace("_", ""),
            *_expanded_aliases(module, aliases),
        }
        for legacy_name in legacy_names:
            nested_target_info = nested_target([legacy_name])
            nested_path = (
                target_paths.get(nested_target_info[0])
                if nested_target_info is not None and nested_target_info[1] == 1
                else None
            )
            legacy_paths.setdefault(legacy_name, nested_path or canonical_path)
    return legacy_paths


def canonicalize_usage(text: str) -> str:
    legacy_paths = _legacy_command_paths()
    if not legacy_paths:
        return text

    commands = "|".join(re.escape(command) for command in sorted(legacy_paths, key=len, reverse=True))
    pattern = re.compile(rf"(?<!\w)(library\s+)({commands})(?![\w-])")

    def replace(match: re.Match) -> str:
        legacy_command = match.group(2)
        canonical_command = legacy_paths[legacy_command]
        canonical_suffix = canonical_command.removeprefix(legacy_command)
        remainder = text[match.end() :]
        is_nested_command = any(
            path.startswith(f"{legacy_command} ")
            and remainder.startswith(path.removeprefix(legacy_command))
            for path in _canonical_nested_paths_for_all_groups()
        )
        if (canonical_suffix and remainder.startswith(canonical_suffix)) or is_nested_command:
            return match.group(0)
        return f"{match.group(1)}{canonical_command}"

    return pattern.sub(replace, text)


def _resolve_target(command: str) -> str | None:
    target = command.replace("_", "-")
    if target in canonical_target_paths():
        return target
    aliases = module_alias_targets()
    return aliases.get(command) or aliases.get(target)


def _target_module(target: str) -> tuple[str, str]:
    target = module_alias_targets().get(target, target)
    for module in modules:
        module_name, function_name = module.rsplit(".", 1)
        if function_name.replace("_", "-") == target:
            return module_name, function_name
    raise KeyError(target)


def command_usage(command: str) -> str:
    command = command.replace("_", "-")
    nested_target_info = nested_target(command.split())
    target = nested_target_info[0] if nested_target_info else module_alias_targets().get(command, command)
    module_name, function_name = _target_module(target)
    module = importlib.import_module(module_name)

    local_usage = getattr(module, "USAGE", {})
    if function_name in local_usage:
        return local_usage[function_name]

    from library import usage as usage_mod

    usage_value = None
    if function_name in {"listen", "media", "read", "view", "watch"}:
        usage_value = usage_mod.play(function_name)
    elif function_name in {"extensions", "mimetypes", "sizes"}:
        usage_value = usage_mod.disk_usage
    elif function_name in {"merge_cp", "merge_mv", "rel_cp", "rel_mv"}:
        usage_value = usage_mod.merge_mv
    elif function_name == "process_audio":
        usage_value = usage_mod.process_ffmpeg
    else:
        usage_aliases = {
            "hacker_news_add": "hn_add",
            "move_list": "mv_list",
            "optimize_db": "optimize",
            "playback_now": "now",
            "playback_next": "next",
            "playback_seek": "seek",
            "playback_stop": "stop",
            "playback_pause": "pause",
            "pushshift_extract": "pushshift",
            "czkawka_dedupe": "dedupe_czkawka",
            "border": "text_border",
            "clean": "text_clean",
        }
        usage_value = getattr(usage_mod, usage_aliases.get(function_name, function_name), "")

    return usage_value if isinstance(usage_value, str) else ""


def canonicalize_usage_for_command(text: str, command: str) -> str:
    text = canonicalize_usage(text)
    if not text:
        return text
    trailing_newline = text.endswith("\n")

    nested_target_info = nested_target(command.split())
    target = nested_target_info[0] if nested_target_info else _resolve_target(command)
    canonical_command = canonical_target_paths().get(target, command.replace("_", "-"))

    lines = text.splitlines()
    known_paths = sorted(_canonical_nested_paths_for_all_groups(), key=len, reverse=True)
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("library "):
            continue

        route = next(
            (
                path
                for path in known_paths
                if stripped == f"library {path}" or stripped.startswith(f"library {path} ")
            ),
            None,
        )
        if route is None:
            break
        suffix = stripped[len(f"library {route}") :]
        lines[index] = f"{line[: len(line) - len(stripped)]}library {canonical_command}{suffix}"
        break
    result = "\n".join(lines)
    return result + "\n" if trailing_newline else result


def _invoke_target(target: str):
    module_name, function_name = _target_module(target)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)()


def _dispatch(args) -> None:
    if hasattr(args, "func"):
        subcommand = " ".join(getattr(args, "_nested_path", []))
        if hasattr(args, "_nested_args"):
            if subcommand:
                sys.argv[0] = f"library {subcommand}"
            sys.argv[1:] = args._nested_args  # noqa: SLF001
        elif len(sys.argv) >= MIN_NESTED_ARGV_LENGTH:
            subcommand = sys.argv[1]
            del sys.argv[1]
            # Present flat aliases using their canonical v4 path in help output too
            canonical_path = canonical_target_paths().get(_resolve_target(subcommand) or "")
            if canonical_path:
                sys.argv[0] = f"library {canonical_path}"
        try:
            return args.func()
        except Exception:
            print("Bug found in", subcommand, " ".join(sys.argv), file=sys.stderr)
            raise

    try:
        log.error("Subcommand %s not found", sys.argv[1])
    except Exception:
        if len(sys.argv) > 1:
            log.error("Invalid args. I see: %s", sys.argv)

    print_help(parser)
    raise SystemExit(1)


def create_subcommands_parser() -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(
        prog="library",
        description="xk media library",
        epilog="Report bugs here: https://github.com/chapmanjacobd/library/issues/new/choose",
        add_help=False,
    )
    subparsers = parser.add_subparsers()

    # this needs to stay inside the function to prevent side-effects during testing
    known_subcommands = [
        "fs",
        "db",
        "media",
        "open",
        "table",
        "tables",
        "tabs",
        "du",
        "search",
        "links",
        "images",
        "torrents",
        "torrent",
    ]

    def set_func(subparser, module_name: str, function_name: str):
        def import_func():
            module = importlib.import_module(module_name)
            return getattr(module, function_name)()

        subparser.set_defaults(func=import_func)

    def add_parser(subparsers, func, aliases=None):
        # copy so registering aliases never mutates the shared `modules` metadata
        aliases = list(aliases or [])

        module_name, function_name = func.rsplit(".", 1)
        name = function_name.replace("_", "-")

        aliases += [
            s.replace("-", "") for s in [name, *aliases] if "-" in s and s.replace("-", "") not in known_subcommands
        ]
        aliases += [
            s.replace("-", "_") for s in [name, *aliases] if "-" in s and s.replace("-", "_") not in known_subcommands
        ]
        known_subcommands.extend([name, *aliases])

        subp = subparsers.add_parser(name, aliases=aliases, add_help=False)

        set_func(subp, module_name, function_name)
        return subp

    # These flat names collide with a nested resource group and are handled by the
    # nested router; registering them again would create unreachable parsers.
    for module, aliases in modules.items():
        if module in NESTED_ONLY_MODULES:
            continue
        add_parser(subparsers, module, aliases)

    parser.add_argument("--version", "-V", action="store_true")

    return parser


parser = create_subcommands_parser()


def _library_with_args(args) -> None:
    original_argv = sys.argv
    try:
        sys.argv = ["lb", *args]
        return library()
    finally:
        sys.argv = original_argv


def library(args=None) -> None:
    if args:
        return _library_with_args(args)

    original_argv = sys.argv[1:]
    if original_argv in (["-h"], ["--help"]):
        print_help(parser)
        raise SystemExit(0)
    if original_argv == ["help"]:
        print_help(parser)
        raise SystemExit(0)

    # `library help <query>` means `library help search <query>` (the v3 spelling)
    if (
        original_argv
        and original_argv[0] == "help"
        and original_argv[1:2] not in ([], ["-h"], ["--help"], ["search"])
    ):
        original_argv = ["help", "search", *original_argv[1:]]

    nested_group = _nested_group(original_argv)
    if (
        original_argv
        and original_argv[-1] in {"-h", "--help"}
        and nested_group is not None
        and isinstance(NESTED_COMMANDS[nested_group], dict)
    ):
        help_node = _nested_tree_node(original_argv[:-1])
        if help_node is not None:
            prefix, node = help_node
            if isinstance(node, dict) and "_target" not in node:
                print(_nested_help(nested_group, prefix=prefix))
                raise SystemExit(0)

    if nested_group and nested_target(original_argv) is None:
        invalid_path = _invalid_nested_path(nested_group, original_argv)
        print(_nested_help(nested_group, invalid_path))
        raise SystemExit(1)

    if nested_group:
        target_info = nested_target(original_argv)
        if target_info is not None:
            target, consumed = target_info
            canonical_path = canonical_target_paths().get(target)
            return _dispatch(
                argparse.Namespace(
                    func=lambda: _invoke_target(target),
                    _nested_path=(canonical_path or " ".join(original_argv[:consumed])).split(),
                    _nested_args=original_argv[consumed:],
                )
            )

    parser.exit_on_error = False  # type: ignore
    try:
        args, _unk = parser.parse_known_args(args)
    except argparse.ArgumentError:
        args = argparse.Namespace(version=False)
    if args.version:
        return print(__version__)

    log.debug("library v%s :: %s", __version__, os.path.realpath(sys.path[0]))
    log.debug(sys.argv)

    return _dispatch(args)


if __name__ == "__main__":
    library()
