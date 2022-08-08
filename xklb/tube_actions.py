from xklb.fs_actions import parse_args, process_actions
from xklb.utils import Subcommand


def tube_watch():
    args = parse_args("tube.db")
    args.action = Subcommand.tubewatch

    process_actions(args)


def tube_listen():
    args = parse_args("tube.db")
    args.action = Subcommand.tubelisten

    process_actions(args)
