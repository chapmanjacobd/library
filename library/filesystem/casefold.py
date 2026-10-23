import argparse
import os
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from library import usage
from library.utils import arggroups, argparse_utils, devices


@dataclass(frozen=True)
class CasefoldAction:
    source: str
    destination: str
    action: str
    reason: str | None = None


def _case_conflicts(entries) -> dict[str, list[str]]:
    grouped = defaultdict(list)
    seen = set()
    for parent, raw_path in entries:
        key = (os.fspath(parent), Path(raw_path).name.casefold())
        path = os.fspath(raw_path)
        if path not in seen:
            grouped[key].append(path)
            seen.add(path)

    conflicts = defaultdict(list)
    for (_, folded_name), paths in grouped.items():
        if len(paths) > 1:
            conflicts[folded_name].extend(paths)

    return {folded_name: sorted(paths) for folded_name, paths in sorted(conflicts.items())}


def find_case_conflicts(root_dir) -> dict[str, list[str]]:
    root = Path(root_dir)
    if not root.is_dir():
        raise NotADirectoryError(os.fspath(root))

    entries = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()

        entries.extend((directory, os.path.join(directory, name)) for name in [*dirnames, *filenames])

    return _case_conflicts(entries)


def _path_entries(path) -> list[tuple[Path, Path]]:
    path = Path(path)
    entries = [(path.parent, path)]
    for parent in path.parents:
        if parent.parent == parent:
            break
        entries.append((parent.parent, parent))
    return entries


def find_case_conflicts_from_paths(paths) -> dict[str, list[str]]:
    entries = []
    seen = set()
    for path in paths:
        if not path or "://" in os.fspath(path):
            continue
        for parent, entry in _path_entries(path):
            key = os.fspath(entry)
            if key not in seen:
                entries.append((parent, entry))
                seen.add(key)
    return _case_conflicts(entries)


def read_paths_from_database(database: str) -> list[str]:
    database_path = Path(database)
    if not database_path.is_file():
        raise FileNotFoundError(os.fspath(database_path))

    uri = f"file:{quote(os.fspath(database_path.resolve()), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(media)")}
        if "path" not in columns:
            message = f"Database table 'media' has no path column: {database}"
            raise ValueError(message)

        where = "WHERE path IS NOT NULL"
        if "time_deleted" in columns:
            where += " AND COALESCE(time_deleted, 0) = 0"
        query = f"SELECT DISTINCT path FROM media {where}"  # noqa: S608 - table and column names are fixed
        return [path for (path,) in connection.execute(query) if path]


def find_case_conflicts_from_db(database: str) -> dict[str, list[str]]:
    return find_case_conflicts_from_paths(read_paths_from_database(database))


def choose_preferred_path(paths) -> str:
    paths = sorted(os.fspath(path) for path in paths)
    mixedcase_paths = [
        path for path in paths if not os.path.basename(path).islower() and not os.path.basename(path).isupper()
    ]
    return mixedcase_paths[0] if mixedcase_paths else paths[0]


def _exists(path: Path) -> bool:
    return os.path.lexists(path)


def _merge_directory(source: Path, destination: Path, *, dry_run: bool, actions: list[CasefoldAction]) -> None:
    if not destination.is_dir():
        actions.append(CasefoldAction(str(source), str(destination), "skip", "destination is not a directory"))
        return

    for child in sorted(source.iterdir(), key=lambda path: path.name):
        target = destination / child.name
        if not _exists(target):
            actions.append(CasefoldAction(str(child), str(target), "move"))
            if not dry_run:
                shutil.move(os.fspath(child), os.fspath(target))
            continue

        if child.is_dir() and not child.is_symlink() and target.is_dir() and not target.is_symlink():
            _merge_directory(child, target, dry_run=dry_run, actions=actions)
        else:
            actions.append(CasefoldAction(str(child), str(target), "skip", "destination already exists"))

    if dry_run or not _exists(source):
        if dry_run or not any(source.iterdir()):
            actions.append(CasefoldAction(str(source), str(destination), "merge"))
    elif not any(source.iterdir()):
        source.rmdir()
        actions.append(CasefoldAction(str(source), str(destination), "merge"))


def apply_case_conflicts(conflicts_map, *, dry_run: bool = True) -> list[CasefoldAction]:
    actions = []
    for folded_name in sorted(conflicts_map):
        paths = [Path(path) for path in conflicts_map[folded_name]]
        paths_by_parent = defaultdict(list)
        for path in paths:
            paths_by_parent[path.parent].append(path)

        for sibling_paths in paths_by_parent.values():
            preferred = Path(choose_preferred_path(sibling_paths))
            if not _exists(preferred):
                actions.extend(
                    CasefoldAction(str(path), str(preferred), "skip", "preferred path is missing")
                    for path in sibling_paths
                    if path != preferred
                )
                continue

            for source in sorted((path for path in sibling_paths if path != preferred), key=os.fspath):
                if not _exists(source):
                    actions.append(CasefoldAction(str(source), str(preferred), "skip", "source path is missing"))
                elif source.is_dir() and not source.is_symlink() and preferred.is_dir() and not preferred.is_symlink():
                    _merge_directory(source, preferred, dry_run=dry_run, actions=actions)
                else:
                    actions.append(
                        CasefoldAction(str(source), str(preferred), "skip", "entries cannot be merged safely")
                    )

    return actions


def print_conflicts(conflicts_map) -> None:
    for folded_name in sorted(conflicts_map):
        print(f"Conflicts for '{folded_name}':")
        for path in conflicts_map[folded_name]:
            print(f"  - {path}")
        print(f"  preferred: {choose_preferred_path(conflicts_map[folded_name])}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.case_conflicts)
    parser.add_argument("directory", nargs="?", help="Root directory to scan")
    parser.add_argument("--db", dest="database", metavar="DATABASE", help="Read paths from a SQLite database")
    parser.add_argument(
        "--apply",
        "--run",
        action="store_true",
        help="Apply safe directory merges instead of only reporting conflicts",
    )
    arggroups.debug(parser)
    args = parser.parse_args(argv)
    if bool(args.directory) == bool(args.database):
        parser.error("provide either DIRECTORY or --db DATABASE")
    return args


def casefold() -> None:
    args = parse_args()
    if args.database:
        conflicts = find_case_conflicts_from_db(args.database)
    else:
        root = os.fspath(args.directory)
        if not os.path.isdir(root):
            message = f"Not a directory: {root}"
            raise SystemExit(message)
        conflicts = find_case_conflicts(root)
    if not conflicts:
        print("No case conflicts found.")
        return

    if not args.apply or args.simulate:
        print_conflicts(conflicts)
        return

    if not args.no_confirm and not devices.confirm(f"Apply safe merges for {len(conflicts)} case conflicts?"):
        print("Cancelled.")
        return

    actions = apply_case_conflicts(conflicts, dry_run=False)
    for action in actions:
        if action.action in {"move", "merge"}:
            print(f"{action.action}\t{action.source}\t{action.destination}")
        elif action.reason:
            print(f"skip\t{action.source}\t{action.destination}\t{action.reason}")


casefold_conflicts = casefold
case_conflicts = casefold
find_conflicts = find_case_conflicts
apply_conflicts = apply_case_conflicts
merge_conflicts = apply_case_conflicts
