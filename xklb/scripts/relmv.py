import argparse, shlex
from collections import OrderedDict
from os.path import commonprefix
from pathlib import Path

from xklb import usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library relmv", usage=usage.relmv)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--test", "--dry-run", action="store_true")

    parser.add_argument("sources", nargs="+", help="one or more source files or directories to move")
    parser.add_argument("dest", help="destination directory")
    args = parser.parse_args()

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def _relmv(args, sources, dest):
    for source in sources:
        abspath = Path(source).expanduser().resolve()

        rel_prefix = commonprefix([abspath, dest])
        try:
            relpath = str(abspath.relative_to(rel_prefix))
        except ValueError:
            relpath = str(abspath.relative_to(Path(rel_prefix).parent))
        target_dir = (dest / relpath).parent

        # remove duplicate path parts
        target_dir = Path(*OrderedDict.fromkeys(target_dir.parts).keys())

        if args.test:
            log.warning("mv %s %s", shlex.quote(str(abspath)), shlex.quote(str(target_dir)))
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            new_path = target_dir / abspath.name
            log.info("%s -> %s", abspath, new_path)
            abspath.rename(new_path)
        except OSError as e:
            if e.errno == 18:  # cross-device move
                log.info("%s ->d %s", abspath, target_dir)
                utils.cmd_interactive("mv", abspath, target_dir)
            elif e.errno == 39:  # target dir not empty
                log.info("%s ->m %s", abspath, dest)
                _relmv(args, abspath.glob("*"), dest)
            elif e.errno == 2:  # FileNotFoundError
                log.error("%s not found", abspath)
            else:
                raise


def relmv() -> None:
    args = parse_args()

    dest = Path(args.dest).expanduser().resolve()
    _relmv(args, args.sources, dest)


if __name__ == "__main__":
    relmv()
