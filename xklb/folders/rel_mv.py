import argparse, shlex
from os.path import commonprefix
from pathlib import Path

from xklb import usage
from xklb.utils import arggroups, argparse_utils, file_utils, path_utils, processes
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library relmv", usage=usage.relmv)
    arggroups.simulate(parser)
    arggroups.debug(parser)

    parser.add_argument("sources", nargs="+", help="one or more source files or directories to move")
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


def rel_move(sources, dest, simulate=False, relative_from=None):
    if relative_from:
        relative_from = Path(relative_from).expanduser().resolve()

    new_paths = []
    for source in sources:
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

        if simulate:
            log.warning("mv %s %s", shlex.quote(str(abspath)), shlex.quote(str(target_dir)))
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        new_path = target_dir / abspath.name
        try:
            log.info("%s -> %s", abspath, new_path)
            abspath.rename(new_path)
            new_paths.append(new_path)
        except OSError as e:
            if e.errno == 2:  # FileNotFoundError
                log.error("%s not found", abspath)
            elif e.errno == 39:  # target dir not empty
                log.info("%s ->m %s", abspath, dest)
                new_paths.extend(rel_move(abspath.glob("*"), dest, simulate=simulate))
            elif e.errno == 18:  # cross-device move
                log.info("%s ->d %s", abspath, target_dir)
                processes.cmd_interactive("mv", str(abspath), str(target_dir))
                new_paths.append(new_path)
            else:
                raise
    return new_paths


def rel_mv() -> None:
    args = parse_args()

    dest = Path(args.dest).expanduser().resolve()

    sources = args.sources
    if args.ext:
        sources = [p for source in sources for p in file_utils.rglob(source, args.ext)[0]]
    rel_move(sources, dest, simulate=args.simulate)


if __name__ == "__main__":
    rel_mv()
