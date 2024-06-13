import argparse, errno, os.path, shlex, shutil
from os.path import commonprefix
from pathlib import Path

from xklb import usage
from xklb.files import sample_compare
from xklb.utils import arggroups, argparse_utils, devices, file_utils, path_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.rel_mv)
    parser.add_argument(
        "--replace",
        "--clobber",
        action=argparse.BooleanOptionalAction,
        help="Overwrite files on path conflict (default: ask to confirm)",
    )
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


def rel_move(sources, dest, simulate=False, relative_from=None, replace=False):
    if relative_from:
        relative_from = [Path(s).expanduser().resolve() for s in relative_from]

    new_paths = []
    for source in sources:
        abspath = Path(source).expanduser().resolve()

        if relative_from:
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
        log.info("%s -> %s", abspath, target_dir)
        try:
            if os.path.exists(new_path):
                if os.path.isdir(new_path):
                    log.info("%s ->m %s", abspath, new_path)
                    new_paths.extend(
                        rel_move(
                            abspath.glob("*"), dest, simulate=simulate, relative_from=relative_from, replace=replace
                        )
                    )
                else:
                    if replace:
                        os.replace(abspath, new_path)
                        new_paths.append(new_path)
                    else:
                        src_stat = os.stat(abspath)
                        dst_stat = os.stat(new_path)
                        is_src_smaller = src_stat.st_size < dst_stat.st_size
                        if os.path.samestat(src_stat, dst_stat):
                            log.error("%s ->x %s same file", abspath, new_path)
                        elif dst_stat.st_size == 0:
                            os.replace(abspath, new_path)
                        elif src_stat.st_size != dst_stat.st_size:
                            log.error(
                                "%s ->x %s source file is %s than dest file conflict",
                                abspath,
                                new_path,
                                "smaller" if is_src_smaller else "larger",
                            )
                            if devices.confirm("Replace destination?"):
                                os.replace(abspath, new_path)
                        elif sample_compare.sample_cmp(abspath, new_path):
                            os.unlink(abspath)
                        else:
                            log.error("%s ->x %s already exists", abspath, new_path)
            else:
                os.rename(abspath, new_path)
                new_paths.append(new_path)
        except OSError as e:
            if e.errno == errno.ENOENT:  # FileNotFoundError
                log.error("%s not found", abspath)
            elif e.errno == errno.EXDEV:  # cross-device move
                log.debug("%s ->d %s", abspath, target_dir)
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
    rel_move(sources, dest, simulate=args.simulate, relative_from=args.relative_from, replace=args.replace)


if __name__ == "__main__":
    rel_mv()
