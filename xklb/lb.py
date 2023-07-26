import argparse, sys

from xklb import __version__, utils
from xklb.consts import SC
from xklb.dl_extract import dl_download
from xklb.fs_extract import fs_add, fs_update
from xklb.gdl_extract import gallery_add, gallery_update
from xklb.hn_extract import hacker_news_add
from xklb.play_actions import filesystem, listen, read, view, watch
from xklb.praw_extract import reddit_add, reddit_update
from xklb.scripts.bigdirs import bigdirs
from xklb.scripts.block import block
from xklb.scripts.christen import christen
from xklb.scripts.cluster_sort import cluster_sort
from xklb.scripts.copy_play_counts import copy_play_counts
from xklb.scripts.dedupe import dedupe
from xklb.scripts.dedupe_db import dedupe_db
from xklb.scripts.disk_usage import disk_usage
from xklb.scripts.download_status import download_status
from xklb.scripts.history import history
from xklb.scripts.merge_dbs import merge_dbs
from xklb.scripts.merge_online_local import merge_online_local
from xklb.scripts.mining.extract_links import extract_links
from xklb.scripts.mining.mpv_watchlater import mpv_watchlater
from xklb.scripts.mining.nouns import nouns
from xklb.scripts.mining.pushshift import pushshift_extract
from xklb.scripts.mining.reddit_selftext import reddit_selftext
from xklb.scripts.move_list import move_list
from xklb.scripts.optimize_db import optimize_db
from xklb.scripts.places_import import places_import
from xklb.scripts.playback_control import playback_next, playback_now, playback_pause, playback_stop
from xklb.scripts.playlists import playlists
from xklb.scripts.redownload import redownload
from xklb.scripts.relmv import relmv
from xklb.scripts.scatter import scatter
from xklb.scripts.streaming_tab_loader import streaming_tab_loader
from xklb.search import search
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
      lb search                Search text and subtitles

      lb read                  Read books
      lb view                  View images

      lb bigdirs               Discover folders which take much room
      lb dedupe                Deduplicate local db files
      lb relmv                 Move files/folders while preserving relative paths
      lb christen              Cleanse files by giving them a new name

      lb mv-list               Reach a target free space by moving data across mount points
      lb scatter               Scatter files across multiple mountpoints (mergerfs balance)

      lb merge-dbs             Merge multiple SQLITE files
      lb copy-play-counts      Copy play counts from multiple SQLITE files

    online media:
      lb tubeadd               Create a tube database; Add playlists
      lb tubeupdate            Fetch new videos from saved playlists

      lb galleryadd            Create a gallery database; Add albums
      lb galleryupdate         Fetch new images from saved playlists

      lb redditadd             Create a reddit database; Add subreddits
      lb redditupdate          Fetch new posts from saved subreddits

    downloads:
      lb download              Download media
      lb redownload            Redownload missing media
      lb block                 Prevent downloading specific URLs
      lb merge-online-local    Merge local and online metadata

    playback:
      lb now                   Print what is currently playing
      lb next                  Play next file
      lb stop                  Stop all playback
      lb pause                 Pause all playback

    statistics:
      lb history               Show some playback statistics
      lb playlists             List added playlists
      lb download-status       Show download status
      lb disk-usage            Print disk usage
      lb mount-stats           Print mount usage

    browser tabs:
      lb tabsadd               Create a tabs database; Add URLs
      lb tabs                  Open your tabs for the day
      lb surf                  Load browser tabs in a streaming way (stdin)

    places:
      lb places-import         Load POIs from Google Maps Google Takeout

    mining:
      lb reddit-selftext       db selftext external links -> db media table
      lb pushshift             Convert Pushshift jsonl.zstd -> reddit.db format (stdin)
      lb hnadd                 Create a hackernews database (this takes a few days)

      lb extract-links         Extract links from lists of web pages

      lb mpv-watchlater        Import timestamps from mpv watchlater to history table

      lb cluster-sort          Lines -> sorted by sentence similarity groups (stdin)
      lb nouns                 Unstructured text -> compound nouns (stdin)
    """


def print_help(parser) -> None:
    print(usage())
    print(parser.epilog)


subcommands = ["fs", "du", "dedupe"]


def consecutive_prefixes(s):
    prefixes = [s[:j] for j in range(5, len(s)) if s[:j] and s[:j] not in subcommands]
    subcommands.extend(prefixes)
    return prefixes


def add_parser(subparsers, name, a=None):
    if a is None:
        a = []
    subcommands.extend([name, *a])
    aliases = a + consecutive_prefixes(name) + utils.conform([consecutive_prefixes(a) for a in a])
    return subparsers.add_parser(name, aliases=aliases, add_help=False)


def create_subcommands_parser() -> argparse.ArgumentParser:
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

    subp_search = add_parser(subparsers, "search", ["s"])
    subp_search.set_defaults(func=search)

    subp_read = add_parser(subparsers, SC.read, ["text", "books", "docs"])
    subp_read.set_defaults(func=read)
    subp_view = add_parser(subparsers, SC.view, ["image", "see", "look"])
    subp_view.set_defaults(func=view)

    subp_filesystem = add_parser(subparsers, SC.filesystem, ["fs"])
    subp_filesystem.set_defaults(func=filesystem)

    subp_bigdirs = add_parser(subparsers, "bigdirs", ["largefolders", "large_folders"])
    subp_bigdirs.set_defaults(func=bigdirs)
    subp_move_list = add_parser(subparsers, "mv-list", ["movelist", "move-list", "move_list"])
    subp_move_list.set_defaults(func=move_list)
    subp_relmv = add_parser(subparsers, "relmv", ["rel-mv", "mvrel", "mv-rel"])
    subp_relmv.set_defaults(func=relmv)

    subp_scatter = add_parser(subparsers, "scatter")
    subp_scatter.set_defaults(func=scatter)
    subp_christen = add_parser(subparsers, "christen")
    subp_christen.set_defaults(func=christen)

    subp_merge_db = add_parser(subparsers, "merge-dbs", ["merge-db", "mergedb", "mergedbs", "merge_db", "merge_dbs"])
    subp_merge_db.set_defaults(func=merge_dbs)
    subp_dedupe_db = add_parser(subparsers, "dedupe-dbs", ["dedupe-db", "dedupedb", "dedupe_db"])
    subp_dedupe_db.set_defaults(func=dedupe_db)
    subp_copy_play_counts = add_parser(subparsers, "copy-play-counts")
    subp_copy_play_counts.set_defaults(func=copy_play_counts)

    subp_dedupe = add_parser(subparsers, "dedupe")
    subp_dedupe.set_defaults(func=dedupe)
    subp_dedupe_local = add_parser(subparsers, "merge-online-local")
    subp_dedupe_local.set_defaults(func=merge_online_local)
    subp_optimize = add_parser(subparsers, "optimize", ["optimize-db"])
    subp_optimize.set_defaults(func=optimize_db)

    subp_tubeadd = add_parser(subparsers, "tubeadd", ["ta", "dladd", "da"])
    subp_tubeadd.set_defaults(func=tube_add)
    subp_tubeupdate = add_parser(subparsers, "tubeupdate", ["dlupdate", "tu"])
    subp_tubeupdate.set_defaults(func=tube_update)

    subp_galleryadd = add_parser(subparsers, "galleryadd", ["gdladd", "ga"])
    subp_galleryadd.set_defaults(func=gallery_add)
    subp_galleryupdate = add_parser(subparsers, "galleryupdate", ["gdlupdate", "gu"])
    subp_galleryupdate.set_defaults(func=gallery_update)

    subp_redditadd = add_parser(subparsers, "redditadd", ["ra"])
    subp_redditadd.set_defaults(func=reddit_add)
    subp_redditupdate = add_parser(subparsers, "redditupdate", ["ru"])
    subp_redditupdate.set_defaults(func=reddit_update)
    subp_pushshift = add_parser(subparsers, "pushshift")
    subp_pushshift.set_defaults(func=pushshift_extract)

    subp_hnadd = add_parser(subparsers, "hnadd")
    subp_hnadd.set_defaults(func=hacker_news_add)

    subp_download = add_parser(subparsers, "download", ["dl"])
    subp_download.set_defaults(func=dl_download)
    subp_block = add_parser(subparsers, "block")
    subp_block.set_defaults(func=block)
    subp_redownload = add_parser(subparsers, "redownload", ["redl"])
    subp_redownload.set_defaults(func=redownload)

    subp_playlist = add_parser(subparsers, "playlists", ["pl", "folders"])
    subp_playlist.set_defaults(func=playlists)
    subp_history = add_parser(subparsers, "history", ["hi", "log"])
    subp_history.set_defaults(func=history)
    subp_download_status = add_parser(subparsers, "download-status", ["ds", "dlstatus"])
    subp_download_status.set_defaults(func=download_status)
    subp_disk_usage = add_parser(subparsers, "disk-usage", ["du", "usage", "diskusage"])
    subp_disk_usage.set_defaults(func=disk_usage)
    subp_mount_stats = add_parser(subparsers, "mount-stats", ["mu", "mount-usage", "mountstats"])
    subp_mount_stats.set_defaults(func=utils.mount_stats)

    subp_playback_now = add_parser(subparsers, "now")
    subp_playback_now.set_defaults(func=playback_now)
    subp_playback_next = add_parser(subparsers, "next")
    subp_playback_next.set_defaults(func=playback_next)
    subp_playback_stop = add_parser(subparsers, "stop")
    subp_playback_stop.set_defaults(func=playback_stop)
    subp_playback_pause = add_parser(subparsers, "pause", ["play"])
    subp_playback_pause.set_defaults(func=playback_pause)

    subp_tabsadd = add_parser(subparsers, "tabsadd")
    subp_tabsadd.set_defaults(func=tabs_add)
    subp_tabs = add_parser(subparsers, "tabs", ["tb"])
    subp_tabs.set_defaults(func=tabs)
    subp_surf = add_parser(subparsers, "surf")
    subp_surf.set_defaults(func=streaming_tab_loader)

    subp_places_import = add_parser(subparsers, "places-import")
    subp_places_import.set_defaults(func=places_import)

    subp_nouns = add_parser(subparsers, "nouns")
    subp_nouns.set_defaults(func=nouns)
    subp_cluster_sort = add_parser(subparsers, "cluster-sort", ["cs", "clustersort", "cluster_sort"])
    subp_cluster_sort.set_defaults(func=cluster_sort)

    subp_mpv_watchlater = add_parser(subparsers, "mpv-watchlater")
    subp_mpv_watchlater.set_defaults(func=mpv_watchlater)

    subp_reddit_selftext = add_parser(subparsers, "reddit-selftext")
    subp_reddit_selftext.set_defaults(func=reddit_selftext)
    subp_nfb_directors = add_parser(subparsers, "extract-links", ["links"])
    subp_nfb_directors.set_defaults(func=extract_links)

    parser.add_argument("--version", "-V", action="store_true")
    return parser


def library(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

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
        return None
    else:
        try:
            log.error("Subcommand %s not found", original_argv[1])
        except Exception:
            if len(original_argv) > 1:
                log.error("Invalid args. I see: %s", original_argv)

        print_help(parser)
        raise SystemExit(1)


if __name__ == "__main__":
    library()
