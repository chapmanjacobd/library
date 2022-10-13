import argparse, sys
from time import sleep

from brotab.api import SingleMediatorAPI
from brotab.main import create_clients, parse_prefix_and_window_id

from xklb import db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library surf",
        usage="""library surf [--count COUNT] [--target-hosts TARGET_HOSTS] [--prefix-window-id PREFIX_WINDOW_ID] [database ...]

    Streaming tab loader: press ctrl+c to stop.

    Currently only stdin is supported:

        cat tabs.txt | library surf -n 5
    """,
    )
    parser.add_argument("database", nargs="?")
    parser.add_argument("--count", "-n", default=4, type=int)
    parser.add_argument("--target-hosts", "--target", default=None, help="Target hosts IP:Port")
    parser.add_argument("--prefix-window-id", default="a", help="Client prefix and (optionally) window id, e.g. b.20")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    if args.database:
        args.db = db.connect(args)
        raise NotImplementedError

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def list_tabs(args):
    api = SingleMediatorAPI(create_clients(args.target_hosts))
    return api.list_tabs([])


def open_tabs(args, urls):
    api = SingleMediatorAPI(create_clients(args.target_hosts))
    _prefix, window_id = parse_prefix_and_window_id(args.prefix_window_id)
    api.open_urls(urls, window_id)


def streaming_tab_loader() -> None:
    args = parse_args()

    initial_count = len(list_tabs(args))
    while True:
        current_count = len(list_tabs(args))
        if current_count < initial_count + args.count:
            urls = [sys.stdin.readline().rstrip() for _ in range(args.count)]
            try:
                open_tabs(args, urls)
            except ConnectionResetError:
                print("open_tabs ConnectionResetError")

        sleep(0.1)


if __name__ == "__main__":
    streaming_tab_loader()
