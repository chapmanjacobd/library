import argparse, logging, sys
from time import sleep

from xklb import db, player, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library surf",
        usage="""library surf [--count COUNT] [--target-hosts TARGET_HOSTS] < stdin

    Streaming tab loader: press ctrl+c to stop.

    Open tabs from a line-delimited file:

        cat tabs.txt | library surf -n 5

    You will likely want to use this setting in `about:config`

        browser.tabs.loadDivertedInBackground = True

    If you prefer GUI, check out https://unli.xyz/tabsender/
    """,
    )
    parser.add_argument("database")
    parser.add_argument("--count", "-n", default=2, type=int)
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
    return args.bt_api.list_tabs([])


def open_tabs(_args, urls):
    for url in urls:
        utils.cmd(player.get_browser(), url)


def streaming_tab_loader() -> None:
    args = parse_args()

    try:
        from brotab.api import SingleMediatorAPI
        from brotab.main import create_clients
    except ModuleNotFoundError:
        raise ModuleNotFoundError(
            "brotab is required for surfing. Install with pip install brotab or pip install xklb[full]"
        )
    else:
        logging.getLogger("brotab").setLevel(log.level)
        args.bt_api = SingleMediatorAPI(create_clients(args.target_hosts))  # type: ignore

    tabs_opened = 0
    initial_count = len(list_tabs(args))
    try:
        while True:
            current_count = len(list_tabs(args))
            if current_count < initial_count + args.count:
                log.debug("[%s < %s]: Opening tab", current_count, initial_count + args.count)
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
