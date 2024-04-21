import argparse
from pathlib import Path

from xklb import usage
from xklb.mediadb import db_history
from xklb.utils import arg_utils, arggroups, consts, db_utils, objects, printing
from xklb.utils.log_utils import log


def parse_args(**kwargs):
    parser = argparse.ArgumentParser(**kwargs)
    arggroups.extractor(parser)

    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()

    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def history_add() -> None:
    args = parse_args(prog="library history-add", usage=usage.history_add)

    history_exists = set()
    history_new = set()
    media_unknown = set()
    for p in arg_utils.gen_paths(args):
        media_id = args.db.pop("select id from media where path = ?", [p])
        if media_id is None:
            media_unknown.add(p)
            if not args.force:
                continue

        if db_history.exists(args, media_id):
            history_exists.add(p)
        else:
            history_new.add(p)

        db_history.add(args, media_ids=[media_id], time_played=consts.APPLICATION_START, mark_done=True)

        printing.print_overwrite(
            f"History: {len(history_new)} new [{len(history_exists)} known {len(media_unknown)} skipped]"
        )


if __name__ == "__main__":
    history_add()
