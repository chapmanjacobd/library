import argparse, importlib, sys, textwrap

from tabulate import tabulate

from xklb import __version__
from xklb.utils import iterables
from xklb.utils.log_utils import log

progs = {
    "Create database subcommands": {
        "fsadd": "Add local media",
        "tubeadd": "Add online video media (yt-dlp)",
        "webadd": "Add open-directory media",
        "galleryadd": "Add online gallery media (gallery-dl)",
        "tabsadd": "Create a tabs database; Add URLs",
        "links_add": "Create a link-scraping database",
        "siteadd": "Auto-scrape website data to SQLITE",
        "redditadd": "Create a reddit database; Add subreddits",
        "pushshift": "Convert pushshift data to reddit.db format (stdin)",
        "hnadd": "Create / Update a Hacker News database",
        "substack": "Backup substack articles",
        "tildes": "Backup tildes comments and topics",
        "places_import": "Import places of interest (POIs)",
    },
    "Update database subcommands": {
        "fsupdate": "Update local media",
        "tubeupdate": "Update online video media",
        "webupdate": "Update open-directory media",
        "galleryupdate": "Update online gallery media",
        "links_update": "Update a link-scraping database",
        "redditupdate": "Update reddit media",
    },
    "Playback subcommands": {
        "watch": "Watch / Listen",
        "now": "Show what is currently playing",
        "next": "Play next file and optionally delete current file",
        "stop": "Stop all playback",
        "pause": "Pause all playback",
        "open_links": "Open links from link dbs",
        "surf": "Auto-load browser tabs in a streaming way (stdin)",
    },
    "Media database subcommands": {
        "tabs": "Open your tabs for the day",
        "block": "Block a channel",
        "playlists": "List stored playlists",
        "download": "Download media",
        "download_status": "Show download status",
        "redownload": "Re-download deleted/lost media",
        "history": "Show some playback statistics",
        "search": "Search captions / subtitles",
    },
    "Text subcommands": {
        "cluster_sort": "Sort text and images by similarity",
        "extract_links": "Extract inner links from lists of web links",
        "extract_text": "Extract human text from lists of web links",
        "markdown_links": "Extract titles from lists of web links",
    },
    "File subcommands": {
        "eda": "Exploratory Data Analysis on table-like files",
        "mcda": "Multi-criteria Ranking for Decision Support",
        "incremental_diff": "Diff large table-like files in chunks",
        "media_check": "Check video and audio files for corruption via ffmpeg",
        "sample_hash": "Calculate a hash based on small file segments",
        "sample_compare": "Compare files using sample-hash and other shortcuts",
    },
    "Folder subcommands": {
        "merge_folders": "Merge two or more file trees",
        "relmv": "Move files preserving parent folder hierarchy",
        "mv_list": "Find specific folders to move to different disks",
        "scatter": "Scatter files between folders or disks",
    },
    "Multi-database subcommands": {
        "merge_dbs": "Merge SQLITE databases",
        "copy_play_counts": "Copy play history",
    },
    "Filesystem Database subcommands": {
        "christen": "Clean filenames",
        "disk_usage": "Show disk usage",
        "mount_stats": "Show some relative mount stats",
        "big_dirs": "Show large folders",
        "search_db": "Search a SQLITE database",
        "optimize": "Re-optimize database",
    },
    "Single database enrichment subcommands": {
        "dedupe_db": "Dedupe SQLITE tables",
        "dedupe_media": "Dedupe similar media",
        "merge_online_local": "Merge online and local data",
        "mpv_watchlater": "Import mpv watchlater files to history",
        "reddit_selftext": "Copy selftext links to media table",
    },
    "Misc subcommands": {
        "export_text": "Export HTML files from SQLite databases",
        "process_audio": "Shrink audio by converting to Opus format",
        "dedupe_czkawka": "Process czkawka diff output",
        "nouns": "Unstructured text -> compound nouns (stdin)",
    },
}


def usage() -> str:
    subcommands_list = []
    for category, category_progs in progs.items():
        subcommands_list.append(f"\n    {category}:\n")
        category_progs_text = tabulate(
            [(key.replace("_", "-"), value) for key, value in category_progs.items()],
            tablefmt="rounded_grid",
            showindex=False,
        )
        subcommands_list.append(textwrap.indent(category_progs_text, "    "))
        subcommands_list.append("\n")

    return f"""xk media library subcommands (v{__version__})
{''.join(subcommands_list)}"""


def print_help(parser) -> None:
    print(usage())
    print(parser.epilog)


def create_subcommands_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lb",
        description="xk media library",
        epilog="Report bugs here: https://github.com/chapmanjacobd/library/issues/new/choose",
        add_help=False,
    )
    subparsers = parser.add_subparsers()

    # this needs to stay inside the function because if create_subcommands_parser() is called twice and if known_subcommands is preserved then the results won't be the same
    known_subcommands = ["fs", "du", "search", "links"]

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

    add_parser(subparsers, "xklb.dl_extract.dl_download", ["dl", "download"])
    add_parser(subparsers, "xklb.fs_extract.fs_add", ["x", "extract"])
    add_parser(subparsers, "xklb.fs_extract.fs_update", ["xu"])
    add_parser(subparsers, "xklb.gdl_extract.gallery_add", ["gdl-add", "ga"])
    add_parser(subparsers, "xklb.gdl_extract.gallery_update", ["gdl-update", "gu"])
    add_parser(subparsers, "xklb.hn_extract.hacker_news_add", ["hn-add"])
    add_parser(subparsers, "xklb.media.dedupe.dedupe_media")
    add_parser(subparsers, "xklb.media.media_check.media_check")
    add_parser(subparsers, "xklb.play_actions.filesystem", ["fs", "open"])
    add_parser(subparsers, "xklb.play_actions.listen", ["lt", "tubelisten", "tl"])
    add_parser(subparsers, "xklb.play_actions.read", ["books", "docs"])
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
    add_parser(subparsers, "xklb.scripts.links_db.links_add", ["links-db"])
    add_parser(subparsers, "xklb.scripts.links_db.links_update")
    add_parser(subparsers, "xklb.scripts.mcda.mcda", ["mcdm", "rank"])
    add_parser(subparsers, "xklb.scripts.merge_dbs.merge_dbs", ["merge-db"])
    add_parser(subparsers, "xklb.scripts.merge_folders.merge_folders", ["merge-folder", "mv"])
    add_parser(subparsers, "xklb.scripts.merge_online_local.merge_online_local")
    add_parser(subparsers, "xklb.scripts.mining.extract_links.extract_links", ["links", "links_extract"])
    add_parser(subparsers, "xklb.scripts.mining.extract_text.extract_text", ["text", "text_extract"])
    add_parser(subparsers, "xklb.scripts.mining.markdown_links.markdown_links", ["markdown-urls"])
    add_parser(subparsers, "xklb.scripts.mining.mpv_watchlater.mpv_watchlater")
    add_parser(subparsers, "xklb.scripts.mining.nouns.nouns", ["nouns"])
    add_parser(subparsers, "xklb.scripts.mining.pushshift.pushshift_extract", ["pushshift"])
    add_parser(subparsers, "xklb.scripts.mining.reddit_selftext.reddit_selftext")
    add_parser(subparsers, "xklb.scripts.mining.substack.substack")
    add_parser(subparsers, "xklb.scripts.mining.tildes.tildes")
    add_parser(subparsers, "xklb.scripts.move_list.move_list", ["mv-list"])
    add_parser(subparsers, "xklb.scripts.open_links.open_links", ["links-open"])
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
    add_parser(subparsers, "xklb.scripts.sample_hash.sample_hash", ["hash", "hash-file"])
    add_parser(subparsers, "xklb.scripts.sample_compare.sample_compare", ["cmp"])
    add_parser(subparsers, "xklb.scripts.scatter.scatter")
    add_parser(subparsers, "xklb.scripts.search_db.search_db", ["s", "sdb", "search-dbs"])
    add_parser(subparsers, "xklb.scripts.streaming_tab_loader.streaming_tab_loader", ["surf"])
    add_parser(subparsers, "xklb.scripts.web_add.web_add", ["web-dir-add"])
    add_parser(subparsers, "xklb.scripts.web_update.web_update", ["web-dir-update"])
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
    parser.exit_on_error = False  # type: ignore
    try:
        args, _unk = parser.parse_known_args(args)
    except argparse.ArgumentError:
        args = argparse.Namespace(version=False)
    if args.version:
        return print(__version__)

    log.info("library v%s", __version__)
    log.info(sys.argv)

    if hasattr(args, "func"):
        if len(sys.argv) >= 2:
            del sys.argv[1]
        return args.func()
    else:
        try:
            log.error("Subcommand %s not found", sys.argv[1])
        except Exception:
            if len(sys.argv) > 1:
                log.error("Invalid args. I see: %s", sys.argv)

        print_help(parser)
        raise SystemExit(1)


if __name__ == "__main__":
    library()
