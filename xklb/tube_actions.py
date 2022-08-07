from xklb.fs_actions import parse_args, process_actions
from xklb.utils import Subcommand


def tube_watch():
    args = parse_args()
    args.action = Subcommand.tubewatch
    if not args.db:
        args.db = "tube_video.db"

    process_actions(args)


def tube_listen():
    args = parse_args()
    args.action = Subcommand.tubelisten
    if not args.db:
        args.db = "tube_audio.db"

    process_actions(args)
