import argparse, importlib, sys, textwrap

from tabulate import tabulate

from xklb import __version__
from xklb.utils import argparse_utils, iterables
from xklb.utils.log_utils import log

progs = {
    "Create database subcommands": {
        "fs_add": "Add local media",
        "tube_add": "Add online video media (yt-dlp)",
        "web_add": "Add open-directory media",
        "gallery_add": "Add online gallery media (gallery-dl)",
        "tabs_add": "Create a tabs database; Add URLs",
        "links_add": "Create a link-scraping database",
        "site_add": "Auto-scrape website data to SQLITE",
        "reddit_add": "Create a reddit database; Add subreddits",
        "hn_add": "Create / Update a Hacker News database",
        "substack": "Backup substack articles",
        "tildes": "Backup tildes comments and topics",
        "places_import": "Import places of interest (POIs)",
        "row_add": "Add arbitrary data to SQLITE",
    },
    "Text subcommands": {
        "cluster_sort": "Sort text and images by similarity",
        "extract_links": "Extract inner links from lists of web links",
        "extract_text": "Extract human text from lists of web links",
        "markdown_links": "Extract titles from lists of web links",
        "nouns": "Unstructured text -> compound nouns (stdin)",
    },
    "Folder subcommands": {
        "merge_folders": "Merge two or more file trees",
        "relmv": "Move files preserving parent folder hierarchy",
        "mv_list": "Find specific folders to move to different disks",
        "scatter": "Scatter files between folders or disks",
        "mount_stats": "Show some relative mount stats",
        "similar_folders": "Find similar folders based on folder name, size, and count",
    },
    "File subcommands": {
        "christen": "Clean file paths",
        "sample_hash": "Calculate a hash based on small file segments",
        "sample_compare": "Compare files using sample-hash and other shortcuts",
        "similar_files": "Find similar files based on filename and size",
    },
    "Tabular data subcommands": {
        "eda": "Exploratory Data Analysis on table-like files",
        "mcda": "Multi-criteria Ranking for Decision Support",
        "incremental_diff": "Diff large table-like files in chunks",
    },
    "Media File subcommands": {
        "media_check": "Check video and audio files for corruption via ffmpeg",
        "process_ffmpeg": "Shrink video/audio to AV1/Opus format (.mkv, .mka)",
        "process_image": "Shrink images by resizing and AV1 image format (.avif)",
    },
    "Multi-database subcommands": {
        "merge_dbs": "Merge SQLITE databases",
        "copy_play_counts": "Copy play history",
    },
    "Filesystem Database subcommands": {
        "disk_usage": "Show disk usage",
        "big_dirs": "Show large folders",
        "search_db": "Search a SQLITE database",
    },
    "Media Database subcommands": {
        "block": "Block a channel",
        "playlists": "List stored playlists",
        "download": "Download media",
        "download_status": "Show download status",
        "redownload": "Re-download deleted/lost media",
        "history": "Show and manage playback history",
        "history_add": "Add history from paths",
        "stats": "Show some event statistics (created, deleted, watched, etc)",
        "search": "Search captions / subtitles",
        "optimize": "Re-optimize database",
    },
    "Playback subcommands": {
        "watch": "Watch / Listen",
        "now": "Show what is currently playing",
        "next": "Play next file and optionally delete current file",
        "stop": "Stop all playback",
        "pause": "Pause all playback",
        "tabs_open": "Open your tabs for the day",
        "links_open": "Open links from link dbs",
        "surf": "Auto-load browser tabs in a streaming way (stdin)",
    },
    "Database enrichment subcommands": {
        "dedupe_db": "Dedupe SQLITE tables",
        "dedupe_media": "Dedupe similar media",
        "merge_online_local": "Merge online and local data",
        "mpv_watchlater": "Import mpv watchlater files to history",
        "reddit_selftext": "Copy selftext links to media table",
        "tabs_shuffle": "Randomize tabs.db a bit",
        "pushshift": "Convert pushshift data to reddit.db format (stdin)",
    },
    "Update database subcommands": {
        "fs_update": "Update local media",
        "tube_update": "Update online video media",
        "web_update": "Update open-directory media",
        "gallery_update": "Update online gallery media",
        "links_update": "Update a link-scraping database",
        "reddit_update": "Update reddit media",
    },
    "Misc subcommands": {
        "export_text": "Export HTML files from SQLite databases",
        "dedupe_czkawka": "Process czkawka diff output",
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

    subcommands = list(iterables.flatten((v.keys() for k, v in progs.items())))
    return f"""library (v{__version__}; {len(subcommands)} subcommands)
{''.join(subcommands_list)}"""


def print_help(parser) -> None:
    print(usage())
    print(parser.epilog)


def create_subcommands_parser() -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(
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

    add_parser(subparsers, "xklb.createdb.fs_add.fs_add", ["x", "extract"])
    add_parser(subparsers, "xklb.createdb.fs_add.fs_update", ["xu"])
    add_parser(subparsers, "xklb.createdb.gallery_add.gallery_add", ["gdl-add", "ga"])
    add_parser(subparsers, "xklb.createdb.gallery_add.gallery_update", ["gdl-update", "gu"])
    add_parser(subparsers, "xklb.createdb.hn_add.hacker_news_add", ["hn-add"])
    add_parser(subparsers, "xklb.createdb.links_add.links_add", ["links-db"])
    add_parser(subparsers, "xklb.createdb.links_add.links_update")
    add_parser(subparsers, "xklb.createdb.places_import.places_import")
    add_parser(subparsers, "xklb.createdb.reddit_add.reddit_add", ["ra"])
    add_parser(subparsers, "xklb.createdb.reddit_add.reddit_update", ["ru"])
    add_parser(subparsers, "xklb.createdb.row_add.row_add", ["add_row"])
    add_parser(subparsers, "xklb.createdb.site_add.site_add", ["sa", "sql-site", "site-sql"])
    add_parser(subparsers, "xklb.createdb.substack.substack")
    add_parser(subparsers, "xklb.createdb.tabs_add.tabs_add")
    add_parser(subparsers, "xklb.createdb.tabs_add.tabs_shuffle")
    add_parser(subparsers, "xklb.createdb.tildes.tildes")
    add_parser(subparsers, "xklb.createdb.tube_add.tube_add", ["ta", "dladd", "da"])
    add_parser(subparsers, "xklb.createdb.tube_add.tube_update", ["dlupdate", "tu"])
    add_parser(subparsers, "xklb.createdb.web_add.web_add", ["web-dir-add"])
    add_parser(subparsers, "xklb.createdb.web_add.web_update", ["web-dir-update"])
    add_parser(subparsers, "xklb.editdb.dedupe_db.dedupe_db", ["dedupe-dbs"])
    add_parser(subparsers, "xklb.editdb.dedupe_media.dedupe_media")
    add_parser(subparsers, "xklb.editdb.merge_online_local.merge_online_local")
    add_parser(subparsers, "xklb.editdb.mpv_watchlater.mpv_watchlater")
    add_parser(subparsers, "xklb.editdb.pushshift.pushshift_extract", ["pushshift"])
    add_parser(subparsers, "xklb.editdb.reddit_selftext.reddit_selftext")
    add_parser(subparsers, "xklb.files.christen.christen")
    add_parser(subparsers, "xklb.files.sample_compare.sample_compare", ["cmp"])
    add_parser(subparsers, "xklb.files.sample_hash.sample_hash", ["hash", "hash-file"])
    add_parser(subparsers, "xklb.files.similar_files.similar_files")
    add_parser(subparsers, "xklb.folders.merge_folders.merge_folders", ["merge-folder", "mv"])
    add_parser(subparsers, "xklb.folders.move_list.move_list", ["mv-list"])
    add_parser(subparsers, "xklb.folders.rel_mv.rel_mv", ["relmv", "mv-rel", "mvrel"])
    add_parser(subparsers, "xklb.folders.scatter.scatter")
    add_parser(subparsers, "xklb.folders.similar_folders.similar_folders")
    add_parser(subparsers, "xklb.folders.mount_stats.mount_stats", ["mu", "mount-usage"])
    add_parser(subparsers, "xklb.folders.big_dirs.big_dirs", ["large-folders"])
    add_parser(subparsers, "xklb.fsdb.disk_usage.disk_usage", ["du", "usage"])
    add_parser(subparsers, "xklb.fsdb.search_db.search_db", ["s", "sdb", "search-dbs"])
    add_parser(subparsers, "xklb.mediadb.block.block")
    add_parser(subparsers, "xklb.mediadb.download.dl_download", ["dl", "download"])
    add_parser(subparsers, "xklb.mediadb.download_status.download_status", ["ds", "dl-status"])
    add_parser(subparsers, "xklb.mediadb.history.history", ["hi", "log"])
    add_parser(subparsers, "xklb.mediadb.history_add.history_add", ["add-history"])
    add_parser(subparsers, "xklb.mediadb.stats.stats")
    add_parser(subparsers, "xklb.mediadb.optimize_db.optimize_db", ["optimize"])
    add_parser(subparsers, "xklb.mediadb.playlists.playlists", ["pl", "folders"])
    add_parser(subparsers, "xklb.mediadb.redownload.redownload", ["re-dl", "re-download"])
    add_parser(subparsers, "xklb.mediadb.search.search", ["sc", "search-captions"])
    add_parser(subparsers, "xklb.mediafiles.media_check.media_check")
    add_parser(subparsers, "xklb.mediafiles.process_ffmpeg.process_ffmpeg", ["process-video", "process-audio"])
    add_parser(subparsers, "xklb.mediafiles.process_image.process_image")
    add_parser(subparsers, "xklb.misc.dedupe_czkawka.czkawka_dedupe", ["dedupe-czkawka"])
    add_parser(subparsers, "xklb.misc.export_text.export_text")
    add_parser(subparsers, "xklb.multidb.copy_play_counts.copy_play_counts")
    add_parser(subparsers, "xklb.multidb.merge_dbs.merge_dbs", ["merge-db"])
    add_parser(subparsers, "xklb.playback.links_open.links_open", ["open-links"])
    add_parser(subparsers, "xklb.playback.play_actions.filesystem", ["fs", "open"])
    add_parser(subparsers, "xklb.playback.play_actions.listen", ["lt", "tubelisten", "tl"])
    add_parser(subparsers, "xklb.playback.play_actions.read", ["books", "docs"])
    add_parser(subparsers, "xklb.playback.play_actions.view", ["image", "see", "look"])
    add_parser(subparsers, "xklb.playback.play_actions.watch", ["wt", "tubewatch", "tw", "entries"])
    add_parser(subparsers, "xklb.playback.playback_control.playback_next", ["next"])
    add_parser(subparsers, "xklb.playback.playback_control.playback_now", ["now"])
    add_parser(subparsers, "xklb.playback.playback_control.playback_pause", ["pause", "play"])
    add_parser(subparsers, "xklb.playback.playback_control.playback_stop", ["stop"])
    add_parser(subparsers, "xklb.playback.surf.streaming_tab_loader", ["surf"])
    add_parser(subparsers, "xklb.playback.tabs_open.tabs_open", ["tb", "tabs", "open_tabs"])
    add_parser(subparsers, "xklb.tablefiles.eda.eda", ["preview"])
    add_parser(subparsers, "xklb.tablefiles.incremental_diff.incremental_diff")
    add_parser(subparsers, "xklb.tablefiles.mcda.mcda", ["mcdm", "rank"])
    add_parser(subparsers, "xklb.text.cluster_sort.cluster_sort", ["cs"])
    add_parser(subparsers, "xklb.text.extract_links.extract_links", ["links", "links_extract"])
    add_parser(subparsers, "xklb.text.extract_text.extract_text", ["text", "text_extract"])
    add_parser(subparsers, "xklb.text.markdown_links.markdown_links", ["markdown-urls"])
    add_parser(subparsers, "xklb.text.nouns.nouns", ["nouns"])

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
