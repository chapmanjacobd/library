import argparse, importlib, os, sys, textwrap

from tabulate import tabulate

from xklb.utils import argparse_utils, iterables
from xklb.utils.log_utils import log

__version__ = "3.0.025"

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
        "substack": "Backup substack articles",
        "tildes": "Backup tildes comments and topics",
        "nicotine_import": "Import paths from nicotine+",
        "places_import": "Import places of interest (POIs)",
        "row_add": "Add arbitrary data to SQLite",
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
        "big_dirs": "Show large folders",
        "similar_folders": "Find similar folders based on folder name, size, and count",
    },
    "File subcommands": {
        "christen": "Clean file paths",
        "sample_hash": "Calculate a hash based on small file segments",
        "sample_compare": "Compare files using sample-hash and other shortcuts",
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
        "images_to_pdf": "Convert folders of images into image PDFs",
        "pdf_edit": "Apply brightness, contrast, saturation, and sharpness adjustments to PDFs",
    },
    "Multi-database subcommands": {
        "merge_dbs": "Merge SQLite databases",
        "copy_play_counts": "Copy play history",
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
    "xklb.createdb.fs_add.fs_add": ["x", "extract"],
    "xklb.createdb.fs_add.fs_update": ["xu"],
    "xklb.createdb.gallery_add.gallery_add": ["gdl-add", "ga"],
    "xklb.createdb.gallery_add.gallery_update": ["gdl-update", "gu"],
    "xklb.createdb.hn_add.hacker_news_add": ["hn-add"],
    "xklb.createdb.links_add.links_add": ["links-db"],
    "xklb.createdb.links_add.links_update": [],
    "xklb.createdb.places_import.places_import": [],
    "xklb.createdb.nicotine_import.nicotine_import": [],
    "xklb.createdb.reddit_add.reddit_add": ["ra"],
    "xklb.createdb.reddit_add.reddit_update": ["ru"],
    "xklb.createdb.row_add.row_add": ["add_row"],
    "xklb.createdb.site_add.site_add": ["sa", "sql-site", "site-sql"],
    "xklb.createdb.substack.substack": [],
    "xklb.createdb.tables_add.tables_add": ["table-add"],
    "xklb.createdb.tabs_add.tabs_add": [],
    "xklb.createdb.tabs_add.tabs_shuffle": [],
    "xklb.createdb.tildes.tildes": [],
    "xklb.createdb.tube_add.tube_add": ["ta", "dladd", "da"],
    "xklb.createdb.tube_add.tube_update": ["dlupdate", "tu"],
    "xklb.createdb.web_add.web_add": ["web-dir-add"],
    "xklb.createdb.web_add.web_update": ["web-dir-update"],
    "xklb.editdb.dedupe_db.dedupe_db": ["dedupe-dbs"],
    "xklb.editdb.dedupe_media.dedupe_media": [],
    "xklb.editdb.merge_online_local.merge_online_local": [],
    "xklb.editdb.mpv_watchlater.mpv_watchlater": [],
    "xklb.editdb.pushshift.pushshift_extract": ["pushshift"],
    "xklb.editdb.reddit_selftext.reddit_selftext": [],
    "xklb.files.christen.christen": [],
    "xklb.files.sample_compare.sample_compare": ["cmp"],
    "xklb.files.sample_hash.sample_hash": ["hash", "hash-file"],
    "xklb.files.similar_files.similar_files": [],
    "xklb.files.llm_map.llm_map": [],
    "xklb.folders.merge_folders.merge_folders": ["merge-folder"],
    "xklb.folders.move_list.move_list": ["mv-list"],
    "xklb.folders.merge_mv.merge_mv": ["mv"],
    "xklb.folders.merge_mv.merge_cp": ["cp"],
    "xklb.folders.merge_mv.rel_mv": ["relmv"],
    "xklb.folders.merge_mv.rel_cp": ["relcp"],
    "xklb.folders.mergerfs_cp.mergerfs_cp": ["cp-mergerfs", "mcp"],
    "xklb.folders.scatter.scatter": [],
    "xklb.folders.similar_folders.similar_folders": [],
    "xklb.folders.mount_stats.mount_stats": ["mu", "mount-usage"],
    "xklb.folders.big_dirs.big_dirs": ["large-folders"],
    "xklb.fsdb.disk_usage.disk_usage": ["du", "usage"],
    "xklb.fsdb.disk_usage.extensions": ["exts"],
    "xklb.fsdb.search_db.search_db": ["s", "sdb", "search-dbs"],
    "xklb.mediadb.block.block": [],
    "xklb.mediadb.download.download": ["dl"],
    "xklb.mediadb.download_status.download_status": ["ds", "dl-status"],
    "xklb.mediadb.history.history": ["hi", "log"],
    "xklb.mediadb.history_add.history_add": ["add-history"],
    "xklb.mediadb.stats.stats": [],
    "xklb.mediadb.optimize_db.optimize_db": ["optimize"],
    "xklb.mediadb.playlists.playlists": ["pl", "folders"],
    "xklb.mediadb.redownload.redownload": ["re-dl", "re-download"],
    "xklb.mediadb.search.search": ["sc", "search-captions"],
    "xklb.mediafiles.media_check.media_check": ["check_media"],
    "xklb.mediafiles.process_media.process_media": ["shrink"],
    "xklb.mediafiles.process_ffmpeg.process_ffmpeg": ["process-video", "video-process"],
    "xklb.mediafiles.process_ffmpeg.process_audio": ["audio-process"],
    "xklb.mediafiles.process_image.process_image": ["image-process"],
    "xklb.mediafiles.process_text.process_text": ["text-process"],
    "xklb.mediafiles.images_to_pdf.images_to_pdf": ["images2pdf"],
    "xklb.mediafiles.pdf_edit.pdf_edit": [],
    "xklb.misc.dedupe_czkawka.czkawka_dedupe": ["dedupe-czkawka"],
    "xklb.misc.export_text.export_text": [],
    "xklb.multidb.copy_play_counts.copy_play_counts": [],
    "xklb.multidb.merge_dbs.merge_dbs": ["merge-db"],
    "xklb.playback.links_open.links_open": ["open-links"],
    "xklb.playback.play_actions.media": [],
    "xklb.playback.play_actions.filesystem": ["fs", "open"],
    "xklb.playback.play_actions.listen": ["lt", "tubelisten", "tl"],
    "xklb.playback.play_actions.read": ["books", "docs"],
    "xklb.playback.play_actions.view": ["images", "see", "look"],
    "xklb.playback.play_actions.watch": ["wt", "tubewatch", "tw", "entries"],
    "xklb.playback.playback_control.playback_next": ["next"],
    "xklb.playback.playback_control.playback_now": ["now"],
    "xklb.playback.playback_control.playback_pause": ["pause", "play"],
    "xklb.playback.playback_control.playback_stop": ["stop"],
    "xklb.playback.playback_control.playback_seek": ["ffwd", "rewind", "seek"],  # TODO: make rewind negative...
    "xklb.playback.surf.streaming_tab_loader": ["surf"],
    "xklb.playback.tabs_open.tabs_open": ["tb", "tabs", "open_tabs"],
    "xklb.tablefiles.eda.eda": ["preview"],
    "xklb.tablefiles.incremental_diff.incremental_diff": [],
    "xklb.tablefiles.columns.columns": [],
    "xklb.tablefiles.markdown_tables.markdown_tables": ["tables", "table"],
    "xklb.tablefiles.mcda.mcda": ["mcdm", "rank"],
    "xklb.tablefiles.plot.plot": ["plots", "chart", "graph"],
    "xklb.text.cluster_sort.cluster_sort": ["cs"],
    "xklb.text.regex_sort.regex_sort": ["rs", "resort"],
    "xklb.text.extract_links.extract_links": ["links", "links_extract"],
    "xklb.text.extract_text.extract_text": ["text", "text_extract"],
    "xklb.text.markdown_links.markdown_links": ["markdown-urls"],
    "xklb.text.expand_links.expand_links": ["search-urls", "search-links"],
    "xklb.text.nouns.nouns": ["noun"],
    "xklb.text.timestamps.dates": ["date"],
    "xklb.text.timestamps.times": ["time"],
    "xklb.text.timestamps.timestamps": ["timestamp", "datetime"],
    "xklb.text.json_keys_rename.json_keys_rename": [],
    "xklb.text.combinations.combinations": ["combos"],
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
    known_subcommands = ["fs", "media", "open", "table", "tables", "tabs", "du", "search", "links", "images"]

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
        sys.argv = ["lb", *args]

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
