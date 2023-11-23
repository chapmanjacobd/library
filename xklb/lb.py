import argparse, importlib, sys

from xklb import __version__
from xklb.utils import iterables
from xklb.utils.log_utils import log


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
      lb dedupe                Deduplicate a media db's media files
      lb czkawka-dedupe        Split-screen czkawka results to decide which to delete
      lb relmv                 Move files/folders while preserving relative paths
      lb christen              Cleanse files by giving them a new name

      lb mv-list               Reach a target free space by moving data across mount points
      lb scatter               Scatter files across multiple mountpoints (mergerfs balance)

      lb search-db             Search a SQLITE file
      lb merge-dbs             Merge multiple SQLITE files
      lb dedupe-dbs            Deduplicate SQLITE tables
      lb copy-play-counts      Copy play counts from multiple SQLITE files

    online media:
      lb tubeadd               Create a tube database; Add playlists
      lb tubeupdate            Fetch new videos from saved playlists

      lb galleryadd            Create a gallery database; Add albums
      lb galleryupdate         Fetch new images from saved playlists

      lb redditadd             Create a reddit database; Add subreddits
      lb redditupdate          Fetch new posts from saved subreddits

      lb tildes                Backup tildes comments and topics
      lb substack              Backup substack articles

      lb merge-online-local    Merge local and online metadata

    downloads:
      lb download              Download media
      lb redownload            Redownload missing media
      lb block                 Prevent downloading specific media

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
      lb siteadd               Create a sites database; Add URLs
      lb surf                  Load browser tabs in a streaming way (stdin)

    places:
      lb places-import         Load POIs from Google Maps Google Takeout

    mining:
      lb eda                   Exploratory Data Analysis on table-like files
      lb mcda                  Multi-criteria ranking on table-like files
      lb incremental-diff      Diff large table-like files in chunks

      lb reddit-selftext       db selftext external links -> db media table
      lb pushshift             Convert Pushshift jsonl.zstd -> reddit.db format (stdin)
      lb hnadd                 Create a hackernews database (this takes a few days)

      lb extract-links         Extract inner links from lists of web pages
      lb markdown-links        Extract titles from lists of web pages

      lb mpv-watchlater        Import timestamps from mpv watchlater to history table

      lb cluster-sort          Lines -> sorted by sentence similarity groups (stdin)
      lb nouns                 Unstructured text -> compound nouns (stdin)
    """


def print_help(parser) -> None:
    print(usage())
    print(parser.epilog)


known_subcommands = ["fs", "du", "search"]


def consecutive_prefixes(s):
    prefixes = [s[:j] for j in range(5, len(s)) if s[:j] and s[:j] not in known_subcommands]
    known_subcommands.extend(prefixes)
    return prefixes


def set_func(subparser, module_name: str, function_name: str):
    def import_func():
        module = importlib.import_module(module_name)
        return getattr(module, function_name)()

    subparser.set_defaults(func=import_func)


def add_parser(subparsers, func, aliases=None):
    if aliases is None:
        aliases = []

    module_name, function_name = func.rsplit(".", 1)
    name = function_name.replace("_", "-")

    aliases += [
        s.replace("-", "") for s in [name] + aliases if "-" in s and s.replace("-", "") not in known_subcommands
    ]
    aliases += [
        s.replace("-", "_") for s in [name] + aliases if "-" in s and s.replace("-", "_") not in known_subcommands
    ]
    known_subcommands.extend([name, *aliases])

    aliases += consecutive_prefixes(name) + iterables.conform([consecutive_prefixes(a) for a in aliases])
    subp = subparsers.add_parser(name, aliases=aliases, add_help=False)

    set_func(subp, module_name, function_name)
    return subp


def create_subcommands_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lb",
        description="xk media library",
        epilog="Report bugs here: https://github.com/chapmanjacobd/library/issues/new/choose",
        add_help=False,
    )
    subparsers = parser.add_subparsers()

    add_parser(subparsers, "xklb.dl_extract.dl_download", ["dl", "download"])
    add_parser(subparsers, "xklb.fs_extract.fs_add", ["x", "extract"])
    add_parser(subparsers, "xklb.fs_extract.fs_update", ["xu"])
    add_parser(subparsers, "xklb.gdl_extract.gallery_add", ["gdl-add", "ga"])
    add_parser(subparsers, "xklb.gdl_extract.gallery_update", ["gdl-update", "gu"])
    add_parser(subparsers, "xklb.hn_extract.hacker_news_add", ["hn-add"])
    add_parser(subparsers, "xklb.media.dedupe.dedupe_media")
    add_parser(subparsers, "xklb.play_actions.filesystem", ["fs", "open"])
    add_parser(subparsers, "xklb.play_actions.listen", ["lt", "tubelisten", "tl"])
    add_parser(subparsers, "xklb.play_actions.read", ["text", "books", "docs"])
    add_parser(subparsers, "xklb.play_actions.view", ["image", "see", "look"])
    add_parser(subparsers, "xklb.play_actions.watch", ["wt", "tubewatch", "tw", "entries"])
    add_parser(subparsers, "xklb.reddit_extract.reddit_add", ["ra"])
    add_parser(subparsers, "xklb.reddit_extract.reddit_update", ["ru"])
    add_parser(subparsers, "xklb.scripts.big_dirs.big_dirs", ["large-folders"])
    add_parser(subparsers, "xklb.scripts.block.block")
    add_parser(subparsers, "xklb.scripts.christen.christen")
    add_parser(subparsers, "xklb.scripts.cluster_sort.cluster_sort", ["cs"])
    add_parser(subparsers, "xklb.scripts.copy_play_counts.copy_play_counts")
    add_parser(subparsers, "xklb.scripts.dedupe_czkawka.czkawka_dedupe", ["dedupe-czkawka"])
    add_parser(subparsers, "xklb.scripts.dedupe_db.dedupe_db", ["dedupe-dbs"])
    add_parser(subparsers, "xklb.scripts.disk_usage.disk_usage", ["du", "usage"])
    add_parser(subparsers, "xklb.scripts.download_status.download_status", ["ds", "dl-status"])
    add_parser(subparsers, "xklb.scripts.eda.eda", ["preview"])
    add_parser(subparsers, "xklb.scripts.export_text.export_text")
    add_parser(subparsers, "xklb.scripts.history.history", ["hi", "log"])
    add_parser(subparsers, "xklb.scripts.incremental_diff.incremental_diff")
    add_parser(subparsers, "xklb.scripts.mcda.mcda", ["mcdm", "rank"])
    add_parser(subparsers, "xklb.scripts.merge_dbs.merge_dbs", ["merge-db"])
    add_parser(subparsers, "xklb.scripts.merge_online_local.merge_online_local")
    add_parser(subparsers, "xklb.scripts.mining.extract_links.extract_links", ["links"])
    add_parser(subparsers, "xklb.scripts.mining.markdown_links.markdown_links", ["markdown-urls"])
    add_parser(subparsers, "xklb.scripts.mining.mpv_watchlater.mpv_watchlater")
    add_parser(subparsers, "xklb.scripts.mining.nouns.nouns", ["nouns"])
    add_parser(subparsers, "xklb.scripts.mining.pushshift.pushshift_extract", ["pushshift"])
    add_parser(subparsers, "xklb.scripts.mining.reddit_selftext.reddit_selftext")
    add_parser(subparsers, "xklb.scripts.mining.substack.substack")
    add_parser(subparsers, "xklb.scripts.mining.tildes.tildes")
    add_parser(subparsers, "xklb.scripts.move_list.move_list", ["mv-list"])
    add_parser(subparsers, "xklb.scripts.optimize_db.optimize_db", ["optimize"])
    add_parser(subparsers, "xklb.scripts.places_import.places_import")
    add_parser(subparsers, "xklb.scripts.playback_control.playback_next", ["next"])
    add_parser(subparsers, "xklb.scripts.playback_control.playback_now", ["now"])
    add_parser(subparsers, "xklb.scripts.playback_control.playback_pause", ["pause", "play"])
    add_parser(subparsers, "xklb.scripts.playback_control.playback_stop", ["stop"])
    add_parser(subparsers, "xklb.scripts.playlists.playlists", ["pl", "folders"])
    add_parser(subparsers, "xklb.scripts.process_audio.process_audio")
    add_parser(subparsers, "xklb.scripts.redownload.redownload", ["re-dl", "re-download"])
    add_parser(subparsers, "xklb.scripts.rel_mv.rel_mv", ["relmv", "mv-rel", "mvrel"])
    add_parser(subparsers, "xklb.scripts.scatter.scatter")
    add_parser(subparsers, "xklb.scripts.search_db.search_db", ["s", "sdb", "search-dbs"])
    add_parser(subparsers, "xklb.scripts.streaming_tab_loader.streaming_tab_loader", ["surf"])
    add_parser(subparsers, "xklb.search.search", ["sc", "search-captions"])
    add_parser(subparsers, "xklb.site_extract.site_add", ["sa", "sql-site", "site-sql"])
    add_parser(subparsers, "xklb.tabs_actions.tabs", ["tb"])
    add_parser(subparsers, "xklb.tabs_extract.tabs_add")
    add_parser(subparsers, "xklb.tube_extract.tube_add", ["ta", "dladd", "da"])
    add_parser(subparsers, "xklb.tube_extract.tube_update", ["dlupdate", "tu"])
    add_parser(subparsers, "xklb.utils.devices.mount_stats", ["mu", "mount-usage"])

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
