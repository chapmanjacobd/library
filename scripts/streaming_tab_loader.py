import argparse, sys
from time import sleep

from xklb import db, utils
from xklb.utils import log

try:
    from brotab.api import SingleMediatorAPI
    from brotab.main import create_clients
except ModuleNotFoundError:
    SingleMediatorAPI = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library surf",
        usage="""library surf [--count COUNT] [--target-hosts TARGET_HOSTS] [--prefix-window-id PREFIX_WINDOW_ID] [database ...]

    Streaming tab loader: press ctrl+c to stop.

    Open tabs from a line-delimited file:

        cat tabs.txt | library surf -n 5

    You will likely want to use this setting in `about:config`

        browser.tabs.loadDivertedInBackground = True

    If you prefer GUI, check out https://unli.xyz/tabsender/
    """,
    )
    parser.add_argument("database", nargs="?")
    parser.add_argument("--count", "-n", default=4, type=int)
    parser.add_argument("--target-hosts", "--target", default=None, help="Target hosts IP:Port")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    if args.database:
        args.db = db.connect(args)
        log.error("Currently only stdin is supported")
        raise NotImplementedError

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def list_tabs(args):
    api = SingleMediatorAPI(create_clients(args.target_hosts))
    return api.list_tabs([])


def open_tabs(args, urls):
    for url in urls:
        utils.cmd("firefox", url)


def streaming_tab_loader() -> None:
    args = parse_args()

    if SingleMediatorAPI is None:
        raise ModuleNotFoundError(
            "brotab is required for surfing. Install with pip install brotab or pip install xklb[full]"
        )

    tabs_opened = 0
    initial_count = len(list_tabs(args))
    try:
        while True:
            current_count = len(list_tabs(args))
            if current_count < initial_count + args.count:
                fill_count = args.count - (current_count - initial_count)
                urls = [sys.stdin.readline().rstrip() for _ in range(fill_count)]
                try:
                    open_tabs(args, urls)
                except ConnectionResetError:
                    print("open_tabs ConnectionResetError")

                tabs_opened += fill_count
            sleep(0.1)
    finally:
        print("Opened", tabs_opened, "tabs")


if __name__ == "__main__":
    streaming_tab_loader()
