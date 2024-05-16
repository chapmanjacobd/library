import argparse, os.path, shlex, shutil
from os.path import commonprefix
from pathlib import Path

from xklb import usage
from xklb.utils import arggroups, argparse_utils, file_utils, path_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library relmv", usage=usage.relmv)
    arggroups.simulate(parser)
    arggroups.debug(parser)

    parser.add_argument(
        "--relative-from", "--relative", "-R", nargs="+", help="Remove matching prefix which matches the most"
    )

    parser.add_argument("--exclude", "-E", nargs="+", action="extend", default=[])

    parser.add_argument(
        "sources",
        nargs="+",
        action=argparse_utils.ArgparseArgsOrStdin,
        help="one or more source files or directories to move",
    )
    parser.add_argument("dest", help="destination directory")
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    return args


def gen_rel_path(source, dest: Path, relative_from=None):
    if relative_from:
        relative_from = Path(relative_from).expanduser().resolve()

    abspath = Path(source).expanduser().resolve()

    if relative_from:
        relpath = str(abspath.relative_to(relative_from))
    else:
        rel_prefix = commonprefix([abspath, dest])
        try:
            relpath = str(abspath.relative_to(rel_prefix))
        except ValueError:
            try:
                relpath = str(abspath.relative_to(Path(rel_prefix).parent))
            except ValueError:
                relpath = str(source)

    target_dir = (dest / relpath).parent
    target_dir = path_utils.dedupe_path_parts(target_dir)
    new_path = target_dir / abspath.name
    return new_path


def strip_drive_path(path):
    return str(path)[len(Path(path).drive) :].lstrip(os.sep)


def relative_from_path(path, start):
    path = strip_drive_path(path)
    start = strip_drive_path(start)
    # log.debug('strip drive: %s\t%s', path, start)

    path = os.path.normpath(path)
    start = os.path.normpath(start)
    # log.debug('normpath: %s\t%s', path, start)

    common_prefix = os.path.commonprefix([path, start])
    # log.debug(common_prefix)

    if common_prefix:
        path = os.path.relpath(path, common_prefix)
        start = os.path.relpath(start, common_prefix)
        # log.debug('relpath: %s\t%s', path, start)

    while start.startswith(os.path.pardir):
        path = str(Path(*Path(path).parts[1:]))
        start = start[len(os.path.pardir + os.sep) :]  # Remove '../' from the start
        # log.debug('join pardir: %s\t%s', path, start)

    relative_path = os.path.relpath(path, start)
    relative_parts = Path(relative_path).parts
    if relative_parts and relative_parts[0] == "..":
        return Path(path)

    return Path(relative_path)


def shortest_relative_from_path(abspath, relative_from_list):
    abspath = Path(abspath)

    shortest_path = None
    shortest_path_length = float("inf")
    for relative_from in relative_from_list:
        try:
            relative_path = relative_from_path(abspath, relative_from)
        except ValueError:
            continue
        else:
            path_length = len(relative_path.parts)
            if path_length < shortest_path_length:
                shortest_path = relative_path
                shortest_path_length = path_length
    return shortest_path or abspath


def rel_move(sources, dest, simulate=False, relative_from=None, relpath=None):
    if relative_from:
        relative_from = [Path(s).expanduser().resolve() for s in relative_from]

    new_paths = []
    for source in sources:
        abspath = Path(source).expanduser().resolve()

        if relpath:
            pass
        elif relative_from:
            relpath = str(shortest_relative_from_path(abspath, relative_from))
        else:
            rel_prefix = commonprefix([abspath, dest])
            try:
                relpath = str(abspath.relative_to(rel_prefix))
            except ValueError:
                try:
                    relpath = str(abspath.relative_to(Path(rel_prefix).parent))
                except ValueError:
                    relpath = str(source)

        target_dir = (dest / relpath).parent
        target_dir = path_utils.dedupe_path_parts(target_dir)

        if simulate:
            log.warning("mv %s %s", shlex.quote(str(abspath)), shlex.quote(str(target_dir)))
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        new_path = target_dir / abspath.name
        try:
            log.info("%s -> %s", abspath, target_dir)
            abspath.rename(new_path)
            new_paths.append(new_path)
        except OSError as e:
            if e.errno == 2:  # FileNotFoundError
                log.error("%s not found", abspath)
            elif e.errno == 39:  # target dir not empty
                log.info("%s ->m %s", abspath, new_path)
                new_paths.extend(rel_move(abspath.glob("*"), dest, simulate=simulate, relpath=relpath))
            elif e.errno == 18:  # cross-device move
                log.debug("%s ->d %s", abspath, target_dir)
                if Path(new_path).is_dir():
                    log.info("%s ->dm %s", abspath, new_path)
                    new_paths.extend(rel_move(abspath.glob("*"), dest, simulate=simulate, relpath=relpath))
                else:
                    shutil.move(str(abspath), str(new_path))  # fallback to shutil
                    new_paths.append(new_path)
            else:
                raise

    return new_paths


def rel_mv() -> None:
    args = parse_args()

    dest = Path(args.dest).expanduser().resolve()

    sources = args.sources
    if args.ext:
        sources = [p for source in sources for p in file_utils.rglob(source, args.ext, args.exclude)[0]]
    rel_move(sources, dest, simulate=args.simulate, relative_from=args.relative_from)


if __name__ == "__main__":
    rel_mv()
