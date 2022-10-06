import argparse, sys

import scripts
from xklb.consts import SC
from xklb.dl_extract import dl_block, dl_download
from xklb.fs_extract import main as fs_add
from xklb.play_actions import filesystem, listen, read, view, watch
from xklb.playback import playback_next, playback_now, playback_pause, playback_stop
from xklb.praw_extract import reddit_add
from xklb.stats import dlstatus, playlists
from xklb.tabs_actions import tabs
from xklb.tabs_extract import tabs_add
from xklb.tube_extract import tube_add, tube_update
from xklb.utils import log


def usage() -> str:
    return """xk media library [lb]

    local media subcommands:
        fsadd                        Create a local media database; Add folders
        listen                       Listen to local and online media
        watch                        Watch local and online media
        read                         Read books
        view                         View images
        filesystem                   Browse files
        bigdirs                      Discover folders which take much room
        dedupe                       Deduplicate audio files
        christen                     Cleanse files by giving them a new name

    online media subcommands:
        tubeadd                      Create a tube database; Add playlists
        tubeupdate                   Add new videos from saved playlists
        redditadd                    Create a reddit database; Add subreddits

    download subcommands:
        download                     Download media
        block                        Prevent downloading specific URLs
        merge-online-local           Merge local and online metadata

    statistics subcommands:
        playlists                    List added playlists
        dlstatus                     Show download status

    playback subcommands:
        now                          Print what is currently playing
        next                         Play next file
        stop                         Stop all playback
        pause                        Pause all playback

    browser tab subcommands:
        tabsadd                      Create a tabs database; Add URLs
        tabs                         Open your tabs for the day
    """


def print_help(parser) -> None:
    print(usage())
    print(parser.epilog)


def lb(args=None) -> None:
    if args:
        sys.argv[2:] = args

    parser = argparse.ArgumentParser(
        prog="lb",
        description="xk media library",
        epilog="Report bugs here: https://github.com/chapmanjacobd/lb/issues/new/choose",
        add_help=False,
    )
    subparsers = parser.add_subparsers()
    subp_extract = subparsers.add_parser("fsadd", aliases=["x", "extract"], add_help=False)
    subp_extract.set_defaults(func=fs_add)

    subp_listen = subparsers.add_parser(SC.listen, aliases=["lt", "tubelisten", "tl"], add_help=False)
    subp_listen.set_defaults(func=listen)
    subp_watch = subparsers.add_parser(SC.watch, aliases=["wt", "tubewatch", "tw", "entries"], add_help=False)
    subp_watch.set_defaults(func=watch)

    subp_read = subparsers.add_parser(SC.read, aliases=["text", "books", "docs"], add_help=False)
    subp_read.set_defaults(func=read)
    subp_view = subparsers.add_parser(SC.view, aliases=["image", "see", "look"], add_help=False)
    subp_view.set_defaults(func=view)

    subp_filesystem = subparsers.add_parser(SC.filesystem, aliases=["fs"], add_help=False)
    subp_filesystem.set_defaults(func=filesystem)

    subp_bigdirs = subparsers.add_parser("bigdirs", aliases=["largefolders", "large_folders"], add_help=False)
    subp_bigdirs.set_defaults(func=scripts.large_folders)
    subp_dedupe = subparsers.add_parser("dedupe", add_help=False)
    subp_dedupe.set_defaults(func=scripts.deduplicate_music)
    subp_christen = subparsers.add_parser("christen", add_help=False)
    subp_christen.set_defaults(func=scripts.rename_invalid_files)
    subp_dedupe_local = subparsers.add_parser("merge-online-local", add_help=False)
    subp_dedupe_local.set_defaults(func=scripts.merge_online_local)
    subp_optimize = subparsers.add_parser("optimize", add_help=False)
    subp_optimize.set_defaults(func=scripts.optimize_db)

    subp_tubeadd = subparsers.add_parser("tubeadd", aliases=["dladd", "ta", "da", "xt"], add_help=False)
    subp_tubeadd.set_defaults(func=tube_add)
    subp_tubeupdate = subparsers.add_parser("tubeupdate", aliases=["dlupdate", "tu", "du"], add_help=False)
    subp_tubeupdate.set_defaults(func=tube_update)

    subp_redditadd = subparsers.add_parser("redditadd", aliases=["ra", "xr"], add_help=False)
    subp_redditadd.set_defaults(func=reddit_add)

    subp_download = subparsers.add_parser("download", aliases=["dl"], add_help=False)
    subp_download.set_defaults(func=dl_download)
    subp_block = subparsers.add_parser("block", aliases=["bl"], add_help=False)
    subp_block.set_defaults(func=dl_block)

    subp_playlist = subparsers.add_parser(
        "playlists", aliases=["playlist", "tubelist", "pl", "folders"], add_help=False
    )
    subp_playlist.set_defaults(func=playlists)
    subp_dlstatus = subparsers.add_parser("dlstatus", aliases=["ds"], add_help=False)
    subp_dlstatus.set_defaults(func=dlstatus)

    subp_playback_now = subparsers.add_parser("now", add_help=False)
    subp_playback_now.set_defaults(func=playback_now)
    subp_playback_next = subparsers.add_parser("next", add_help=False)
    subp_playback_next.set_defaults(func=playback_next)
    subp_playback_stop = subparsers.add_parser("stop", add_help=False)
    subp_playback_stop.set_defaults(func=playback_stop)
    subp_playback_pause = subparsers.add_parser("pause", add_help=False)
    subp_playback_pause.set_defaults(func=playback_pause)

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
    if len(sys.argv) >= 2:
        del sys.argv[1]

    if hasattr(args, "func"):
        args.func()
    else:
        try:
            print("Subcommand", original_argv[1], "not found")
        except Exception:
            print("Invalid args. I see:", original_argv)

        print_help(parser)


def main() -> None:
    lb()


if __name__ == "__main__":
    main()
