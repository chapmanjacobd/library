import argparse, sys

import scripts
from xklb import __version__, utils
from xklb.consts import SC
from xklb.dl_extract import dl_block, dl_download
from xklb.fs_extract import fs_add, fs_update
from xklb.hn_extract import hacker_news_add
from xklb.play_actions import filesystem, listen, read, view, watch
from xklb.playback import playback_next, playback_now, playback_pause, playback_stop
from xklb.praw_extract import reddit_add, reddit_update
from xklb.stats import dlstatus, playlists
from xklb.tabs_actions import tabs
from xklb.tabs_extract import tabs_add
from xklb.tube_extract import tube_add, tube_update
from xklb.utils import log


def usage() -> str:
    return f"""xk media library subcommands (v{__version__})

    local media:
      lb fsadd                 Create a local media database; Add folders
      lb fsupdate              Refresh database: add new files, mark deleted

      lb listen                Listen to local and online media
      lb watch                 Watch local and online media
      lb read                  Read books
      lb view                  View images

      lb bigdirs               Discover folders which take much room
      lb dedupe                Deduplicate local db files

      lb christen              Cleanse files by giving them a new name

    online media:
      lb tubeadd               Create a tube database; Add playlists
      lb tubeupdate            Fetch new videos from saved playlists

      lb redditadd             Create a reddit database; Add subreddits
      lb redditupdate          Fetch new posts from saved subreddits

    downloads:
      lb download              Download media
      lb block                 Prevent downloading specific URLs
      lb merge-dbs             Merge multiple SQLITE files
      lb merge-online-local    Merge local and online metadata

    playback:
      lb now                   Print what is currently playing
      lb next                  Play next file
      lb stop                  Stop all playback
      lb pause                 Pause all playback

    statistics:
      lb playlists             List added playlists
      lb dlstatus              Show download status

    browser tabs:
      lb tabsadd               Create a tabs database; Add URLs
      lb tabs                  Open your tabs for the day
      lb surf                  Load browser tabs in a streaming way (stdin)

    mining:
      lb reddit-selftext       Stored selftext external links -> db media table
      lb pushshift             Convert Pushshift jsonl.zstd -> reddit.db format (stdin)
      lb nfb-films             NFB Director links -> film links (stdin)
      lb nouns                 Unstructured text -> compound nouns (stdin)
      lb hnadd                 Create a hackernews database (this takes a few days)
    """


def print_help(parser) -> None:
    print(usage())
    print(parser.epilog)


subcommands = ["fs"]


def consecutive_prefixes(s):
    prefixes = list(s[:j] for j in range(5, len(s)) if s[:j] and s[:j] not in subcommands)
    subcommands.extend(prefixes)
    return prefixes


def add_parser(subparsers, name, a=None):
    if a is None:
        a = []
    subcommands.extend([name] + a)
    aliases = a + consecutive_prefixes(name) + utils.conform([consecutive_prefixes(a) for a in a])
    return subparsers.add_parser(name, aliases=aliases, add_help=False)


def create_subcommands_parser():
    parser = argparse.ArgumentParser(
        prog="lb",
        description="xk media library",
        epilog="Report bugs here: https://github.com/chapmanjacobd/library/issues/new/choose",
        add_help=False,
    )
    subparsers = parser.add_subparsers()
    subp_fsadd = add_parser(subparsers, "fsadd", ["x", "extract"])
    subp_fsadd.set_defaults(func=fs_add)
    subp_fsupdate = add_parser(subparsers, "fsupdate", ["xu"])
    subp_fsupdate.set_defaults(func=fs_update)

    subp_watch = add_parser(subparsers, SC.watch, ["wt", "tubewatch", "tw", "entries"])
    subp_watch.set_defaults(func=watch)
    subp_listen = add_parser(subparsers, SC.listen, ["lt", "tubelisten", "tl"])
    subp_listen.set_defaults(func=listen)

    subp_read = add_parser(subparsers, SC.read, ["text", "books", "docs"])
    subp_read.set_defaults(func=read)
    subp_view = add_parser(subparsers, SC.view, ["image", "see", "look"])
    subp_view.set_defaults(func=view)

    subp_filesystem = add_parser(subparsers, SC.filesystem, ["fs"])
    subp_filesystem.set_defaults(func=filesystem)

    subp_bigdirs = add_parser(subparsers, "bigdirs", ["largefolders", "large_folders"])
    subp_bigdirs.set_defaults(func=scripts.bigdirs)
    subp_dedupe = add_parser(subparsers, "dedupe")
    subp_dedupe.set_defaults(func=scripts.deduplicate_db)
    subp_christen = add_parser(subparsers, "christen")
    subp_christen.set_defaults(func=scripts.rename_invalid_paths)
    subp_merge_db = add_parser(subparsers, "merge-dbs")
    subp_merge_db.set_defaults(func=scripts.merge_dbs)
    subp_dedupe_local = add_parser(subparsers, "merge-online-local")
    subp_dedupe_local.set_defaults(func=scripts.merge_online_local)
    subp_optimize = add_parser(subparsers, "optimize")
    subp_optimize.set_defaults(func=scripts.optimize_db)

    subp_tubeadd = add_parser(subparsers, "tubeadd", ["dladd", "ta", "da", "xt"])
    subp_tubeadd.set_defaults(func=tube_add)
    subp_tubeupdate = add_parser(subparsers, "tubeupdate", ["dlupdate", "tu", "du"])
    subp_tubeupdate.set_defaults(func=tube_update)

    subp_redditadd = add_parser(subparsers, "redditadd", ["ra", "xr"])
    subp_redditadd.set_defaults(func=reddit_add)
    subp_redditupdate = add_parser(subparsers, "redditupdate", ["ru", "xru"])
    subp_redditupdate.set_defaults(func=reddit_update)
    subp_pushshift = add_parser(subparsers, "pushshift", ["ps"])
    subp_pushshift.set_defaults(func=scripts.pushshift_extract)

    subp_hnadd = add_parser(subparsers, "hnadd")
    subp_hnadd.set_defaults(func=hacker_news_add)

    subp_download = add_parser(subparsers, "download", ["dl"])
    subp_download.set_defaults(func=dl_download)
    subp_block = add_parser(subparsers, "block")
    subp_block.set_defaults(func=dl_block)

    subp_playlist = add_parser(subparsers, "playlists", ["pl", "folders"])
    subp_playlist.set_defaults(func=playlists)
    subp_dlstatus = add_parser(subparsers, "dlstatus", ["ds"])
    subp_dlstatus.set_defaults(func=dlstatus)

    subp_playback_now = add_parser(subparsers, "now")
    subp_playback_now.set_defaults(func=playback_now)
    subp_playback_next = add_parser(subparsers, "next")
    subp_playback_next.set_defaults(func=playback_next)
    subp_playback_stop = add_parser(subparsers, "stop")
    subp_playback_stop.set_defaults(func=playback_stop)
    subp_playback_pause = add_parser(subparsers, "pause")
    subp_playback_pause.set_defaults(func=playback_pause)

    subp_tabsadd = add_parser(subparsers, "tabsadd")
    subp_tabsadd.set_defaults(func=tabs_add)
    subp_tabs = add_parser(subparsers, "tabs", ["tb"])
    subp_tabs.set_defaults(func=tabs)
    subp_surf = add_parser(subparsers, "surf", ["browse", "load"])
    subp_surf.set_defaults(func=scripts.streaming_tab_loader)

    subp_nouns = add_parser(subparsers, "nouns")
    subp_nouns.set_defaults(func=scripts.nouns)

    subp_reddit_selftext = add_parser(subparsers, "reddit-selftext", ["rst"])
    subp_reddit_selftext.set_defaults(func=scripts.parse_reddit_selftext)
    subp_nfb_directors = add_parser(subparsers, "nfb-films")
    subp_nfb_directors.set_defaults(func=scripts.nfb_films)

    parser.add_argument("--version", "-V", action="store_true")
    return parser


def library(args=None) -> None:
    if args:
        sys.argv[2:] = args

    parser = create_subcommands_parser()
    args, _unk = parser.parse_known_args(args)
    if args.version:
        return print(__version__)

    log.info("library v%s", __version__)
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


if __name__ == "__main__":
    library()
