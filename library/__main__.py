import argparse, importlib, os, sys, textwrap

from tabulate import tabulate

from library.utils import argparse_utils, iterables
from library.utils.log_utils import log

__version__ = "3.0.116"

progs = {
    "Create database subcommands": {
        "fs_add": "Add local media",
        "tube_add": "Add online video media (yt-dlp)",
        "web_add": "Add open-directory media",
        "gallery_add": "Add online gallery media (gallery-dl)",
        "tabs_add": "Create a tabs database; Add URLs",
        "links_add": "Create a link-scraping database",
        "site_add": "Auto-scrape website data to SQLite",
        "tables_add": "Add table-like data to SQLite",
        "reddit_add": "Create a reddit database; Add subreddits",
        "hn_add": "Create / Update a Hacker News database",
        "getty_add": "Create / Update a Getty Museum database",
        "substack": "Backup substack articles",
        "tildes": "Backup tildes comments and topics",
        "nicotine_import": "Import paths from nicotine+",
        "places_import": "Import places of interest (POIs)",
        "row_add": "Add arbitrary data to SQLite",
        "computers_add": "Add computer info to SQLite",
        "torrents_add": "Add torrent info to SQLite",
    },
    "Text subcommands": {
        "cluster_sort": "Sort text and images by similarity",
        "regex_sort": "Sort text by regex split and corpus comparison",
        "extract_links": "Extract inner links from lists of web links",
        "extract_text": "Extract human text from lists of web links",
        "markdown_links": "Extract titles from lists of web links",
        "expand_links": "Expand search urls with query text",
        "nouns": "Unstructured text -> compound nouns (stdin)",
        "dates": "Unstructured text -> dates",
        "times": "Unstructured text -> times",
        "timestamps": "Unstructured text -> timestamps",
        "json_keys_rename": "Rename JSON keys by substring match",
        "combinations": "Enumerate possible combinations",
    },
    "Folder subcommands": {
        "merge_mv": "Move files and merge folders in BSD/rsync style, rename if possible",
        "merge_folders": "Merge two or more file trees, check for conflicts before merging",
        "mergerfs_cp": "cp files with reflink on mergerfs",
        "scatter": "Scatter files between folders or disks",
        "mv_list": "Find specific folders to move to different disks",
        "mount_stats": "Show some relative mount stats",
        "disk_free": "Show system-wide disk usage",
        "big_dirs": "Show large folders",
        "similar_folders": "Find similar folders based on folder name, size, and count",
    },
    "File subcommands": {
        "christen": "Clean file paths",
        "sample_hash": "Calculate a hash based on small file segments",
        "sample_compare": "Compare files using sample-hash and other shortcuts",
        "files_info": "Find files by mimetype and size",
        "similar_files": "Find similar files based on filename and size",
        "llm_map": "Run LLMs across multiple files",
    },
    "Tabular data subcommands": {
        "eda": "Exploratory Data Analysis on table-like files",
        "mcda": "Multi-criteria Ranking for Decision Support",
        "plot": "Plot table-like files. A CLI interface to matplotlib",
        "markdown_tables": "Print markdown tables from table-like files",
        "columns": "Print columns of table-like files",
        "incremental_diff": "Diff large table-like files in chunks",
    },
    "Media File subcommands": {
        "media_check": "Check video and audio files for corruption via ffmpeg",
        "process_media": "Estimate and execute potential disk space savings",
        "process_ffmpeg": "Shrink video/audio to AV1/Opus format (.mkv, .mka)",
        "process_image": "Shrink images to AV1 image format (.avif)",
        "process_text": "Shrink documents to HTML+AV1 image format (requires Calibre)",
        "unardel": "Extract from archives and delete all associated multi-part archive files",
        "images_to_pdf": "Convert folders of images into image PDFs",
        "pdf_edit": "Apply brightness, contrast, saturation, and sharpness adjustments to PDFs",
        "torrents_start": "Start torrents (qBittorrent-nox)",
    },
    "Multi-database subcommands": {
        "merge_dbs": "Merge SQLite databases",
        "copy_play_counts": "Copy play history",
        "allocate_torrents": "Use computers.db and torrents.db to allocate torrents",
    },
    "Filesystem Database subcommands": {
        "disk_usage": "Show disk usage",
        "search_db": "Search a SQLite database",
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
        "seek": "Set playback to a certain time, fast-forward or rewind",
        "stop": "Stop all playback",
        "pause": "Pause all playback",
        "tabs_open": "Open your tabs for the day",
        "links_open": "Open links from link dbs",
        "surf": "Auto-load browser tabs in a streaming way (stdin)",
        "torrents_info": "List torrents (qBittorrent-nox)",
        "torrents_remaining": "Overview of torrents by drive (qBittorrent-nox)",
    },
    "Database enrichment subcommands": {
        "dedupe_db": "Dedupe SQLite tables",
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


modules = {
    "library.createdb.computers_add.computers_add": ["computer-add", "pc-add", "ssh-add"],
    "library.createdb.fs_add.fs_add": ["filesystem-add", "x", "extract"],
    "library.createdb.fs_add.fs_update": ["filesystem-update", "xu"],
    "library.createdb.gallery_add.gallery_add": ["gdl-add", "ga"],
    "library.createdb.gallery_add.gallery_update": ["gdl-update", "gu"],
    "library.createdb.hn_add.hacker_news_add": ["hn-add"],
    "library.createdb.getty_add.getty_add": [],
    "library.createdb.links_add.links_add": ["links-db"],
    "library.createdb.links_add.links_update": [],
    "library.createdb.places_import.places_import": [],
    "library.createdb.nicotine_import.nicotine_import": [],
    "library.createdb.reddit_add.reddit_add": ["ra"],
    "library.createdb.reddit_add.reddit_update": ["ru"],
    "library.createdb.row_add.row_add": ["add_row"],
    "library.createdb.site_add.site_add": ["sa", "sql-site", "site-sql"],
    "library.createdb.substack.substack": [],
    "library.createdb.tables_add.tables_add": ["table-add"],
    "library.createdb.tabs_add.tabs_add": [],
    "library.createdb.tabs_add.tabs_shuffle": [],
    "library.createdb.tildes.tildes": [],
    "library.createdb.torrents_add.torrents_add": ["torrent-add"],
    "library.createdb.tube_add.tube_add": ["ta", "dladd", "da"],
    "library.createdb.tube_add.tube_update": ["dlupdate", "tu"],
    "library.createdb.web_add.web_add": ["web-dir-add"],
    "library.createdb.web_add.web_update": ["web-dir-update"],
    "library.editdb.dedupe_db.dedupe_db": ["dedupe-dbs"],
    "library.editdb.dedupe_media.dedupe_media": [],
    "library.editdb.merge_online_local.merge_online_local": [],
    "library.editdb.mpv_watchlater.mpv_watchlater": [],
    "library.editdb.pushshift.pushshift_extract": ["pushshift"],
    "library.editdb.reddit_selftext.reddit_selftext": [],
    "library.files.christen.christen": [],
    "library.files.sample_compare.sample_compare": ["cmp"],
    "library.files.sample_hash.sample_hash": ["hash", "hash-file"],
    "library.files.similar_files.similar_files": [],
    "library.files.llm_map.llm_map": [],
    "library.folders.merge_folders.merge_folders": ["merge-folder"],
    "library.folders.move_list.move_list": ["mv-list"],
    "library.folders.merge_mv.merge_mv": ["mv"],
    "library.folders.merge_mv.merge_cp": ["cp"],
    "library.folders.merge_mv.rel_mv": ["relmv"],
    "library.folders.merge_mv.rel_cp": ["relcp"],
    "library.folders.mergerfs_cp.mergerfs_cp": ["cp-mergerfs", "mcp"],
    "library.folders.scatter.scatter": [],
    "library.folders.similar_folders.similar_folders": [],
    "library.folders.mount_stats.disk_free": ["df", "free"],
    "library.folders.mount_stats.mount_stats": ["mu", "mount-usage"],
    "library.folders.big_dirs.big_dirs": ["large-folders"],
    "library.fsdb.files_info.files_info": ["fs", "files", "filesystem"],
    "library.fsdb.disk_usage.disk_usage": ["du", "usage"],
    "library.fsdb.disk_usage.extensions": ["exts"],
    "library.fsdb.disk_usage.mimetypes": ["types"],
    "library.fsdb.disk_usage.sizes": ["size"],
    "library.fsdb.search_db.search_db": ["s", "sdb", "search-dbs"],
    "library.mediadb.block.block": [],
    "library.mediadb.download.download": ["dl"],
    "library.mediadb.download_status.download_status": ["ds", "dl-status"],
    "library.mediadb.history.history": ["hi", "log"],
    "library.mediadb.history_add.history_add": ["add-history"],
    "library.mediadb.stats.stats": [],
    "library.mediadb.optimize_db.optimize_db": ["optimize"],
    "library.mediadb.playlists.playlists": ["pl", "folders"],
    "library.mediadb.redownload.redownload": ["re-dl", "re-download"],
    "library.mediadb.search.search": ["sc", "search-captions"],
    "library.mediafiles.media_check.media_check": ["check_media"],
    "library.mediafiles.process_media.process_media": ["shrink"],
    "library.mediafiles.process_ffmpeg.process_ffmpeg": ["process-video", "video-process"],
    "library.mediafiles.process_ffmpeg.process_audio": ["audio-process"],
    "library.mediafiles.process_image.process_image": ["image-process"],
    "library.mediafiles.unardel.unardel": ["unarchive", "unar"],
    "library.mediafiles.process_text.process_text": ["text-process"],
    "library.mediafiles.images_to_pdf.images_to_pdf": ["images2pdf"],
    "library.mediafiles.pdf_edit.pdf_edit": [],
    "library.mediafiles.torrents_start.torrents_start": ["torrent-start"],
    "library.misc.dedupe_czkawka.czkawka_dedupe": ["dedupe-czkawka"],
    "library.misc.export_text.export_text": [],
    "library.multidb.copy_play_counts.copy_play_counts": [],
    "library.multidb.merge_dbs.merge_dbs": ["merge-db"],
    "library.multidb.allocate_torrents.allocate_torrents": [],
    "library.playback.links_open.links_open": ["open-links"],
    "library.playback.play_actions.media": ["db", "open"],
    "library.playback.play_actions.listen": ["lt", "tubelisten", "tl"],
    "library.playback.play_actions.read": ["books", "docs"],
    "library.playback.play_actions.view": ["images", "see", "look"],
    "library.playback.play_actions.watch": ["wt", "tubewatch", "tw", "entries"],
    "library.playback.playback_control.playback_next": ["next"],
    "library.playback.playback_control.playback_now": ["now"],
    "library.playback.playback_control.playback_pause": ["pause", "play"],
    "library.playback.playback_control.playback_seek": ["ffwd", "rewind", "seek"],  # TODO: make rewind negative...
    "library.playback.playback_control.playback_stop": ["stop"],
    "library.playback.surf.streaming_tab_loader": ["surf"],
    "library.playback.tabs_open.tabs_open": ["tb", "tabs", "open_tabs"],
    "library.playback.torrents_info.torrents_info": ["torrent-info", "torrents", "torrent"],
    "library.playback.torrents_remaining.torrents_remaining": ["torrent-remaining"],
    "library.tablefiles.eda.eda": ["preview"],
    "library.tablefiles.incremental_diff.incremental_diff": [],
    "library.tablefiles.columns.columns": [],
    "library.tablefiles.markdown_tables.markdown_tables": ["tables", "table"],
    "library.tablefiles.mcda.mcda": ["mcdm", "rank"],
    "library.tablefiles.plot.plot": ["plots", "chart", "graph"],
    "library.text.cluster_sort.cluster_sort": ["cs"],
    "library.text.regex_sort.regex_sort": ["rs", "resort"],
    "library.text.extract_links.extract_links": ["links", "links_extract"],
    "library.text.extract_text.extract_text": ["text", "text_extract"],
    "library.text.markdown_links.markdown_links": ["markdown-urls"],
    "library.text.expand_links.expand_links": ["search-urls", "search-links"],
    "library.text.nouns.nouns": ["noun"],
    "library.text.timestamps.dates": ["date"],
    "library.text.timestamps.times": ["time"],
    "library.text.timestamps.timestamps": ["timestamp", "datetime"],
    "library.text.json_keys_rename.json_keys_rename": [],
    "library.text.combinations.combinations": ["combos"],
}


def create_subcommands_parser() -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(
        prog="library",
        description="xk media library",
        epilog="Report bugs here: https://github.com/chapmanjacobd/library/issues/new/choose",
        add_help=False,
    )
    subparsers = parser.add_subparsers()

    # this needs to stay inside the function to prevent side-effects during testing
    known_subcommands = [
        "fs",
        "db",
        "media",
        "open",
        "table",
        "tables",
        "tabs",
        "du",
        "search",
        "links",
        "images",
        "torrents",
        "torrent",
    ]

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
            s.replace("-", "") for s in [name, *aliases] if "-" in s and s.replace("-", "") not in known_subcommands
        ]
        aliases += [
            s.replace("-", "_") for s in [name, *aliases] if "-" in s and s.replace("-", "_") not in known_subcommands
        ]
        known_subcommands.extend([name, *aliases])

        # aliases += consecutive_prefixes(name) + iterables.conform([consecutive_prefixes(a) for a in aliases])
        subp = subparsers.add_parser(name, aliases=aliases, add_help=False)

        set_func(subp, module_name, function_name)
        return subp

    for module, aliases in modules.items():
        add_parser(subparsers, module, aliases)

    parser.add_argument("--version", "-V", action="store_true")

    return parser


parser = create_subcommands_parser()


def library(args=None) -> None:
    if args:
        original_argv = sys.argv
        try:
            sys.argv = ["lb", *args]
            return library()
        finally:
            sys.argv = original_argv

    parser.exit_on_error = False  # type: ignore
    try:
        args, _unk = parser.parse_known_args(args)
    except argparse.ArgumentError:
        args = argparse.Namespace(version=False)
    if args.version:
        return print(__version__)

    log.info("library v%s :: %s", __version__, os.path.realpath(sys.path[0]))
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
