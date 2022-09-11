import argparse, sys

import scripts
from xklb.fs_actions import filesystem, listen, watch
from xklb.fs_extract import main as fs_add
from xklb.playback import playback_next, playback_now, playback_stop
from xklb.subtitle import main as subtitle
from xklb.tabs_actions import tabs
from xklb.tabs_extract import tabs_add
from xklb.tube_actions import tube_list, tube_listen, tube_watch
from xklb.tube_extract import tube_add, tube_update
from xklb.utils import SC, log


def lb_usage():
    return """xk media library [lb]

    local media subcommands:
      fsadd [extract, xr]          Create a local media database; Add folders
      subtitle [sub]               Find subtitles for local media
      listen [lt]                  Listen to local media
      watch [wt]                   Watch local media
      filesystem [fs]              Browse files
      bigdirs [largefolders]       View folders which take up much room
      dedupe                       Deduplicate audio files

    online media subcommands:
      tubeadd [ta, xt]             Create a tube database; Add playlists
      tubeupdate [tu]              Get new videos from saved playlists
      tubelist [playlists]         List added playlists
      tubewatch [tw, entries]      Watch the tube
      tubelisten [tl]              Listen to the tube

    playback subcommands:
      now                          Print what is currently playing
      next                         Play next file
      stop                         Stop all playback

    browser tab subcommands:
      tabsadd                      Create a tabs database; Add URLs
      tabs [tabswatch, tb]         Open your tabs for the day
    """


def print_help(parser):
    print(lb_usage())
    print(parser.epilog)


def lb(args=None):
    if args:
        sys.argv[2:] = args

    parser = argparse.ArgumentParser(
        prog="lb",
        description="xk media library",
        epilog="Report bugs here: https://github.com/chapmanjacobd/lb/issues/new/choose",
        add_help=False,
    )
    subparsers = parser.add_subparsers()
    subp_extract = subparsers.add_parser("fsadd", aliases=["xr", "extract"], add_help=False)
    subp_extract.set_defaults(func=fs_add)
    subp_subtitle = subparsers.add_parser("subtitle", aliases=["sub"], add_help=False)
    subp_subtitle.set_defaults(func=subtitle)

    subp_listen = subparsers.add_parser(SC.listen, aliases=["lt"], add_help=False)
    subp_listen.set_defaults(func=listen)
    subp_watch = subparsers.add_parser(SC.watch, aliases=["wt"], add_help=False)
    subp_watch.set_defaults(func=watch)
    subp_filesystem = subparsers.add_parser(SC.filesystem, aliases=["fs"], add_help=False)
    subp_filesystem.set_defaults(func=filesystem)

    subp_bigdirs = subparsers.add_parser("bigdirs", aliases=["largefolders", "large_folders"], add_help=False)
    subp_bigdirs.set_defaults(func=scripts.large_folders)

    subp_dedupe = subparsers.add_parser("dedupe", add_help=False)
    subp_dedupe.set_defaults(func=scripts.deduplicate_music)

    subp_tubelist = subparsers.add_parser("tubelist", aliases=["playlist", "playlists"], add_help=False)
    subp_tubelist.set_defaults(func=tube_list)
    subp_tubeadd = subparsers.add_parser("tubeadd", aliases=["ta", "xt"], add_help=False)
    subp_tubeadd.set_defaults(func=tube_add)
    subp_tubeupdate = subparsers.add_parser("tubeupdate", aliases=["tu"], add_help=False)
    subp_tubeupdate.set_defaults(func=tube_update)

    subp_tubewatch = subparsers.add_parser(SC.tubewatch, aliases=["tw", "tube", "entries"], add_help=False)
    subp_tubewatch.set_defaults(func=tube_watch)
    subp_tubelisten = subparsers.add_parser(SC.tubelisten, aliases=["tl"], add_help=False)
    subp_tubelisten.set_defaults(func=tube_listen)

    subp_playback_now = subparsers.add_parser("now", add_help=False)
    subp_playback_now.set_defaults(func=playback_now)
    subp_playback_next = subparsers.add_parser("next", add_help=False)
    subp_playback_next.set_defaults(func=playback_next)
    subp_playback_stop = subparsers.add_parser("stop", add_help=False)
    subp_playback_stop.set_defaults(func=playback_stop)

    subp_tabsadd = subparsers.add_parser("tabsadd", add_help=False)
    subp_tabsadd.set_defaults(func=tabs_add)
    subp_tabs = subparsers.add_parser("tabs", aliases=["tabswatch", "tb"], add_help=False)
    subp_tabs.set_defaults(func=tabs)

    parser.add_argument("--version", "-V", action="store_true")
    args, _unk = parser.parse_known_args(args)
    if args.version:
        from xklb import __version__

        return print(__version__)

    log.info(sys.argv)
    original_argv = sys.argv
    if len(sys.argv) > 1:
        del sys.argv[1]

    if hasattr(args, "func"):
        args.func()
    else:
        try:
            print("Subcommand", original_argv[1], "not found")
        except Exception:
            print("Invalid args. I see:", original_argv)

        print_help(parser)


def main():
    lb()


if __name__ == "__main__":
    main()
