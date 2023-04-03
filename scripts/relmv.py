import argparse, shlex
from os.path import commonprefix
from pathlib import Path

from xklb import utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        usage="""library relmv [--dry-run] SOURCE ... DEST

    Move files/folders without losing hierarchy metadata
"""
    )
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--test", "--dry-run", action="store_true")

    parser.add_argument("sources", nargs="+", help="one or more source files or directories to move")
    parser.add_argument("dest", help="destination directory")
    args = parser.parse_args()

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def relmv() -> None:
    args = parse_args()

    dest = Path(args.dest).expanduser().resolve()
    for source in args.sources:
        abspath = Path(source).expanduser().resolve()

        try:
            relpath = str(abspath.relative_to(commonprefix([abspath, dest])))
        except ValueError:
            relpath = str(abspath.relative_to(Path(commonprefix([abspath, dest])).parent))
        target_dir = (dest / relpath).parent

        if args.test:
            print("mv", shlex.quote(str(abspath)), shlex.quote(str(target_dir)))
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                abspath.rename(target_dir / abspath.name)
            except OSError as e:
                if e.errno == 18:
                    utils.cmd_interactive("mv", abspath, target_dir)
                else:
                    raise e


if __name__ == "__main__":
    relmv()
