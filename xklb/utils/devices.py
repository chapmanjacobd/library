import argparse, os, platform, random, shutil, sys
from typing import Dict, List, Union

from xklb.utils.log_utils import log


def get_ip_of_chromecast(device_name) -> str:
    from pychromecast import discovery

    cast_infos, browser = discovery.discover_listed_chromecasts(friendly_names=[device_name])
    browser.stop_discovery()
    if not cast_infos:
        log.error("Target chromecast device not found")
        raise SystemExit(53)

    return cast_infos[0].host


def clear_input() -> None:
    if platform.system() == "Linux":
        from termios import TCIFLUSH, tcflush

        tcflush(sys.stdin, TCIFLUSH)
    elif platform.system() == "Darwin":
        import select

        while select.select([sys.stdin], [], [], 0.01) == ([sys.stdin], [], []):
            sys.stdin.read(1)
    elif platform.system() == "Windows":
        if getattr(clear_input, "kbhit", None) is None:
            from msvcrt import getch, kbhit  # type: ignore

            clear_input.kbhit = kbhit
            clear_input.getch = getch

        # Try to flush the buffer
        while clear_input.kbhit():
            clear_input.getch()


def confirm(*args, **kwargs) -> bool:
    from rich import prompt

    clear_input()
    return prompt.Confirm.ask(*args, **kwargs, default=False)


def set_readline_completion(list_) -> None:
    try:
        import readline
    except ModuleNotFoundError:
        # "Windows not supported"
        return

    def create_completer(list_):
        def list_completer(_text, state):
            line = readline.get_line_buffer()

            if not line:
                min_depth = min([s.count(os.sep) for s in list_]) + 1  # type: ignore
                result_list = [c + " " for c in list_ if c.count(os.sep) <= min_depth]
                random.shuffle(result_list)
                return result_list[:25][state]
            else:
                match_list = [s for s in list_ if s.startswith(line)]
                min_depth = min([s.count(os.sep) for s in match_list]) + 1  # type: ignore
                result_list = [c + " " for c in match_list if c.count(os.sep) <= min_depth]
                random.shuffle(result_list)
                return result_list[:15][state]

        return list_completer

    readline.set_completer(create_completer(list_))
    readline.set_completer_delims("\t")
    readline.parse_and_bind("tab: complete")
    return


def get_mount_stats(src_mounts) -> List[Dict[str, Union[str, int]]]:
    mount_space = []
    total_used = 1
    total_free = 1
    grand_total = 1
    for src_mount in src_mounts:
        total, used, free = shutil.disk_usage(src_mount)
        total_used += used
        total_free += free
        grand_total += total
        mount_space.append((src_mount, used, free, total))

    return [
        {"mount": mount, "used": used / total_used, "free": free / total_free, "total": total / grand_total}
        for mount, used, free, total in mount_space
    ]


def mount_stats() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("mounts", nargs="+")
    args = parser.parse_args()
    space = get_mount_stats(args.mounts)

    print("Relative disk utilization:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['used'] * 80)} {d['used']:.1%}")

    print("\nRelative free space:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['free'] * 80)} {d['free']:.1%}")
