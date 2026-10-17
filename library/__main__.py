import argparse, difflib, importlib, os, re, sys, textwrap

from tabulate import tabulate

from library._version import __version__
from library.utils import argparse_utils
from library.utils.log_utils import log

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
        "links_download": "Download links from lists of web links",
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
        "filesystem": "Find files by mimetype and size",
        "similar_files": "Find similar files based on filename and size",
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
        "torrents_dump": "Print torrent file info",
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
        "help": "Search subcommands and help text",
    },
}


def usage() -> str:
    grouped_commands = _command_catalog()

    tables = []
    for category, commands in grouped_commands:
        tables.append(f"\n    {category}:\n")
        table = tabulate(commands, tablefmt="rounded_grid", showindex=False)
        tables.append(textwrap.indent(table, "    "))
        tables.append("\n")

    count = len(_canonical_nested_paths_for_all_groups())
    return f"library (v{__version__}; {count} subcommands)\n{''.join(tables)}"


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
    "library.fsdb.filesystem.filesystem": ["files-info"],
    "library.fsdb.disk_usage.disk_usage": ["du", "usage"],
    "library.fsdb.disk_usage.extensions": ["exts"],
    "library.fsdb.disk_usage.mimetypes": ["types"],
    "library.fsdb.disk_usage.sizes": ["size"],
    "library.fsdb.search_db.search_db": ["s", "sdb", "search-dbs"],
    "library.mediadb.block.block": [],
    "library.mediadb.download.download": ["dl"],
    "library.mediadb.download.download_database": [],
    "library.mediadb.download_status.download_status": ["ds", "dl-status"],
    "library.mediadb.history.history": ["hi", "log"],
    "library.mediadb.history_add.history_add": ["add-history"],
    "library.mediadb.stats.stats": [],
    "library.mediadb.optimize_db.optimize_db": ["optimize"],
    "library.mediadb.playlists.playlists": ["pl"],
    "library.mediadb.redownload.redownload": ["re-dl", "re-download"],
    "library.mediadb.search.search": ["sc", "search-captions"],
    "library.mediafiles.media_check.media_check": ["check_media"],
    "library.mediafiles.process_media.process_media": [],
    "library.mediafiles.process_ffmpeg.process_ffmpeg": ["process-video", "video-process"],
    "library.mediafiles.process_ffmpeg.process_audio": ["audio-process"],
    "library.mediafiles.process_image.process_image": ["image-process"],
    "library.mediafiles.unardel.unardel": ["unarchive", "unar"],
    "library.mediafiles.process_text.process_text": ["text-process"],
    "library.mediafiles.images_to_pdf.images_to_pdf": ["images2pdf"],
    "library.mediafiles.pdf_edit.pdf_edit": [],
    "library.mediafiles.torrents_dump.torrents_dump": ["torrent-dump"],
    "library.mediafiles.torrents_start.torrents_start": ["torrent-start"],
    "library.misc.dedupe_czkawka.czkawka_dedupe": ["dedupe-czkawka"],
    "library.misc.export_text.export_text": [],
    "library.misc.search_help.search_help": ["h", "help"],
    "library.multidb.copy_play_counts.copy_play_counts": [],
    "library.multidb.merge_dbs.merge_dbs": ["merge-db"],
    "library.multidb.allocate_torrents.allocate_torrents": [],
    "library.playback.links_open.links_open": ["open-links"],
    "library.playback.play_actions.media": ["open"],
    "library.playback.play_actions.listen": ["lt", "tubelisten", "tl"],
    "library.playback.play_actions.read": ["books"],
    "library.playback.play_actions.view": ["images", "see", "look"],
    "library.playback.play_actions.watch": ["wt", "tubewatch", "tw", "entries"],
    "library.playback.playback_control.playback_next": ["next"],
    "library.playback.playback_control.playback_now": ["now"],
    "library.playback.playback_control.playback_pause": ["pause"],
    "library.playback.playback_control.playback_seek": ["ffwd", "rewind", "seek"],  # TODO: make rewind negative...
    "library.playback.playback_control.playback_stop": ["stop"],
    "library.playback.tabs_open.tabs_open": ["tb", "open_tabs"],
    "library.playback.torrents_info.torrents_info": ["torrent-info"],
    "library.playback.torrents_remaining.torrents_remaining": ["torrent-remaining"],
    "library.tablefiles.eda.eda": ["preview"],
    "library.tablefiles.incremental_diff.incremental_diff": ["diff"],
    "library.tablefiles.columns.columns": [],
    "library.tablefiles.markdown_tables.markdown_tables": [],
    "library.tablefiles.mcda.mcda": ["mcdm", "rank"],
    "library.tablefiles.plot.plot": ["plots", "chart", "graph"],
    "library.text.cluster_sort.cluster_sort": ["cs"],
    "library.text.regex_sort.regex_sort": ["rs", "resort"],
    "library.text.extract_links.extract_links": ["links_extract"],
    "library.text.extract_links.links_download": [],
    "library.text.extract_text.extract_text": ["text_extract"],
    "library.text.markdown_links.markdown_links": ["markdown-urls"],
    "library.text.expand_links.expand_links": ["search-urls", "search-links"],
    "library.text.nouns.nouns": ["noun"],
    "library.text.timestamps.dates": ["date"],
    "library.text.timestamps.times": ["time"],
    "library.text.timestamps.timestamps": ["timestamp", "datetime"],
    "library.text.json_keys_rename.json_keys_rename": [],
    "library.text.combinations.combinations": ["combos"],
}


NESTED_COMMANDS = {
    "play": {
        "media": "media",
        "video": "watch",
        "audio": "listen",
        "text": "read",
        "images": "view",
    },
    "playback": {
        "next": "playback-next",
        "now": "playback-now",
        "pause": "playback-pause",
        "seek": "playback-seek",
        "stop": "playback-stop",
    },
    "database": {
        "add": {
            "filesystem": "fs-add",
            "video": "tube-add",
            "web": "web-add",
            "gallery": "gallery-add",
            "tabs": "tabs-add",
            "links": "links-add",
            "tables": "tables-add",
            "reddit": "reddit-add",
            "getty": "getty-add",
            "computers": "computers-add",
            "torrents": "torrents-add",
            "row": "row-add",
            "site": "site-add",
            "substack": "substack",
            "tildes": "tildes",
            "hackernews": "hacker-news-add",
        },
        "update": {
            "filesystem": "fs-update",
            "video": "tube-update",
            "web": "web-update",
            "gallery": "gallery-update",
            "links": "links-update",
            "reddit": "reddit-update",
        },
        "import": {
            "nicotine": "nicotine-import",
            "places": "places-import",
            "pushshift": "pushshift-extract",
            "mpv-watchlater": "mpv-watchlater",
        },
        "enrich": {"reddit-selftext": "reddit-selftext"},
        "merge": {"_target": "merge-dbs", "online-local": "merge-online-local"},
        "copy": {"play-counts": "copy-play-counts"},
        "dedupe": {"_target": "dedupe-db", "media": "dedupe-media"},
        "export": {"html": "export-text"},
        "search": "search-db",
        "optimize": "optimize-db",
        "download": {"_target": "download-database", "status": "download-status", "block": "block"},
        "history": {"_target": "history", "add": "history-add"},
        "playlists": "playlists",
        "stats": "stats",
        "redownload": "redownload",
    },
    "shrink": {
        "media": "process-media",
        "video": "process-ffmpeg",
        "audio": "process-audio",
        "image": "process-image",
        "text": "process-text",
    },
    "captions": "search",
    "download": "download",
    "torrent": {
        "allocate": "allocate-torrents",
        "info": "torrents-info",
        "start": "torrents-start",
        "remaining": "torrents-remaining",
        "dump": "torrents-dump",
    },
    "links": {
        "open": "links-open",
        "extract": "extract-links",
        "download": "links-download",
    },
    "tabs": {
        "shuffle": "tabs-shuffle",
        "open": "tabs-open",
    },
    "table": {
        "analyze": "eda",
        "markdown": "markdown-tables",
        "columns": "columns",
        "plot": "plot",
        "rank": "mcda",
        "diff": "incremental-diff",
    },
    "filesystem": {
        "list": "filesystem",
        "usage": {
            "_target": "disk-usage",
            "extensions": "extensions",
            "mimetypes": "mimetypes",
            "sizes": "sizes",
        },
        "mounts": {
            "stats": "mount-stats",
            "free": "disk-free",
        },
    },
    "file": {
        "hash": "sample-hash",
        "compare": "sample-compare",
        "similar": "similar-files",
        "normalize": "christen",
        "check": "media-check",
        "dedupe": {"czkawka": "czkawka-dedupe"},
    },
    "folder": {
        "similar": "similar-folders",
        "copy": {"mergerfs": "mergerfs-cp"},
        "scatter": "scatter",
        "large": "big-dirs",
        "move": {"list": "mv-list"},
        "merge": {
            "move": "merge-mv",
            "copy": "merge-cp",
            "relative-move": "relmv",
            "relative-copy": "relcp",
        },
    },
    "document": {
        "convert": {"images": {"pdf": "images-to-pdf"}},
        "adjust": {"pdf": "pdf-edit"},
    },
    "json": {"rename-keys": "json-keys-rename"},
    "archive": {"extract": "unardel"},
    "help": {"search": "search-help"},
    "text": {
        "extract": "extract-text",
        "sort": {"regex": "regex-sort", "cluster": "cluster-sort"},
        "markdown": {"links": "markdown-links"},
        "expand": {"links": "expand-links"},
        "nouns": "nouns",
        "dates": "dates",
        "times": "times",
        "timestamps": "timestamps",
        "combinations": "combinations",
    },
}

NESTED_GROUP_ALIASES = {
    "db": "database",
    "doc": "document",
    "docs": "document",
    "fs": "filesystem",
    "files": "file",
}

NESTED_COMMAND_ALIASES = {
    "fs": "filesystem",
    "ls": "list",
    "explore": "analyze",
}

NESTED_DESCRIPTIONS = {
    "play media": "Play media of any supported type",
    "play video": "Watch video",
    "play audio": "Listen to audio",
    "play text": "Read text",
    "play images": "View images",
    "filesystem usage extensions": "Show disk usage grouped by file extension",
    "filesystem usage mimetypes": "Show disk usage grouped by MIME type",
    "filesystem usage sizes": "Show disk usage grouped by file size",
    "shrink audio": "Shrink audio to Opus",
    "folder merge copy": "Copy files and merge folders",
    "folder merge relative-move": "Move files while preserving relative paths",
    "folder merge relative-copy": "Copy files while preserving relative paths",
    "database download": "Download media recorded in a database",
}

for _group in NESTED_COMMANDS:
    _group_alias = _group.removesuffix("s") if _group.endswith("s") else f"{_group}s"
    NESTED_GROUP_ALIASES.setdefault(_group_alias, _group)


PREFERRED_NESTED_PATHS = {
    "filesystem": "filesystem list",
    "disk-usage": "filesystem usage",
    "extensions": "filesystem usage extensions",
    "mimetypes": "filesystem usage mimetypes",
    "sizes": "filesystem usage sizes",
}


def _canonical_nested_paths(
    group: str,
    command_tree,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    paths = []

    def walk(current, current_prefix: tuple[str, ...]) -> None:
        if isinstance(current, str):
            paths.append(" ".join((group, *current_prefix)))
            return

        if "_target" in current:
            paths.append(" ".join((group, *current_prefix)))
        for command, target in current.items():
            if command != "_target":
                walk(target, (*current_prefix, command))

    walk(command_tree, prefix)
    return paths


def _canonical_nested_paths_for_all_groups() -> list[str]:
    return [
        path
        for group, command_tree in NESTED_COMMANDS.items()
        for path in _canonical_nested_paths(group, command_tree)
    ]


def _expanded_aliases(module: str, aliases) -> list[str]:
    """Aliases plus the hyphen-less/underscore spellings argparse also accepts.

    Computed on demand instead of mutating the shared `modules` metadata.
    """
    name = module.rsplit(".", 1)[1].replace("_", "-")
    expanded = []
    for alias in (name, *aliases):
        if "-" in alias:
            expanded.append(alias.replace("-", ""))
            expanded.append(alias.replace("-", "_"))
    return [*aliases, *expanded]


def _module_alias_targets() -> dict[str, str]:
    targets = {}
    for module, aliases in modules.items():
        target = module.rsplit(".", 1)[1].replace("_", "-")
        for alias in _expanded_aliases(module, aliases):
            targets.setdefault(alias, target)
    return targets


def _nested_target_canonical(path: list[str]) -> tuple[str, int] | None:
    if not path:
        return None

    group = path[0]
    command_tree = NESTED_COMMANDS.get(group)
    if isinstance(command_tree, str):
        return command_tree, 1
    if not isinstance(command_tree, dict):
        return None

    current = command_tree
    consumed = 1
    for part in path[1:]:
        if not isinstance(current, dict) or part not in current:
            break
        current = current[part]
        consumed += 1
        if isinstance(current, str):
            return current, consumed

    if isinstance(current, dict) and "_target" in current:
        return current["_target"], consumed
    return None


def _nested_target(path: list[str]) -> tuple[str, int] | None:
    if not path:
        return None

    canonical_path = [
        NESTED_GROUP_ALIASES.get(path[0], path[0]),
        *[NESTED_COMMAND_ALIASES.get(part, part) for part in path[1:]],
    ]
    target = _nested_target_canonical(canonical_path)
    if target is not None:
        return target

    # Also accept compact spellings such as `db fs update` for `database update filesystem`
    # (the resource and the operation swapped), regardless of which group alias was used.
    if len(canonical_path) >= 3:
        return _nested_target_canonical(
            [canonical_path[0], canonical_path[2], canonical_path[1], *canonical_path[3:]]
        )
    return None


def _nested_group(path: list[str]) -> str | None:
    """Return the canonical resource group for a token, including aliases.

    Group names and their aliases always win over same-named flat commands so that
    invalid subcommands get the helpful `Unknown command` diagnostic instead of a
    generic top-level `Subcommand not found` error.
    """
    if not path:
        return None

    group = NESTED_GROUP_ALIASES.get(path[0], path[0])
    if group not in NESTED_COMMANDS:
        return None
    return group


def _invalid_nested_path(group: str, path: list[str]) -> list[str] | None:
    command_tree = NESTED_COMMANDS.get(group)
    if not isinstance(command_tree, dict) or not path:
        return None

    canonical_path = [group, *[NESTED_COMMAND_ALIASES.get(part, part) for part in path[1:]]]
    current = command_tree
    for index, part in enumerate(canonical_path[1:], start=1):
        if part in {"-h", "--help"}:
            return None
        if not isinstance(current, dict) or part not in current:
            return canonical_path[: index + 1]
        current = current[part]
        if isinstance(current, str):
            return None
    return None


def _nested_tree_node(path: list[str]) -> tuple[tuple[str, ...], object] | None:
    if not path:
        return None

    group = NESTED_GROUP_ALIASES.get(path[0], path[0])
    command_tree = NESTED_COMMANDS.get(group)
    if command_tree is None:
        return None

    current = command_tree
    prefix = []
    for part in path[1:]:
        part = NESTED_COMMAND_ALIASES.get(part, part)
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
        prefix.append(part)
    return tuple(prefix), current


def _nested_help(
    group: str,
    invalid_path: list[str] | None = None,
    prefix: tuple[str, ...] = (),
) -> str:
    command_tree = NESTED_COMMANDS[group]
    if isinstance(command_tree, str):
        return f"usage: library {group} DATABASE [optional args]"

    current = command_tree
    for part in prefix:
        if not isinstance(current, dict):
            return f"usage: library {group} <command> [optional args]"
        current = current[part]

    command_name = " ".join((group, *prefix))
    lines = [f"usage: library {command_name} <command> [optional args]", "", "Commands:"]
    prefix_text = f"{command_name} "
    lines.extend(
        f"  {path.removeprefix(prefix_text)}"
        for path in _canonical_nested_paths(group, current, prefix)
    )
    if invalid_path:
        relative = " ".join(invalid_path[1:])
        choices = [
            path.removeprefix(prefix_text)
            for path in _canonical_nested_paths(group, current, prefix)
        ]
        suggestion = difflib.get_close_matches(relative, choices, n=1, cutoff=0.4)
        message = [f"Unknown command: {' '.join(invalid_path)}"]
        if suggestion:
            message.append(f"Did you mean: {command_name} {suggestion[0]}?")
        lines = [*message, "", *lines]
    return "\n".join(lines)


def _canonical_target_paths() -> dict[str, str]:
    target_paths = {}
    for path in _canonical_nested_paths_for_all_groups():
        target = _nested_target(path.split())
        if target is not None:
            target_paths.setdefault(target[0], path)
    for target, path in PREFERRED_NESTED_PATHS.items():
        if _nested_target(path.split()) == (target, len(path.split())):
            target_paths[target] = path
    return target_paths


def _target_descriptions() -> dict[str, str]:
    descriptions = {}
    for category_progs in progs.values():
        for command, description in category_progs.items():
            target = _resolve_target(command)
            if target is not None:
                descriptions.setdefault(target, description)
    return descriptions


def _command_catalog() -> list[tuple[str, list[tuple[str, str]]]]:
    target_paths = _canonical_target_paths()
    target_descriptions = _target_descriptions()
    grouped_commands = []
    seen = set()

    for category, category_progs in progs.items():
        commands = []
        for command, description in category_progs.items():
            target = _resolve_target(command)
            path = target_paths.get(target) if target else command.replace("_", "-")
            if path in seen:
                continue
            seen.add(path)
            commands.append((path, description))
        if commands:
            grouped_commands.append((category, commands))

    other_commands = []
    for path in _canonical_nested_paths_for_all_groups():
        if path in seen:
            continue
        target_info = _nested_target(path.split())
        target = target_info[0] if target_info else None
        description = NESTED_DESCRIPTIONS.get(path) or target_descriptions.get(target)
        if description is None:
            description = f"Run the {path} command"
        other_commands.append((path, description))
    if other_commands:
        grouped_commands.append(("Other subcommands", other_commands))

    return grouped_commands


def _module_canonical_paths() -> dict[str, str]:
    """Map each implementation module to the canonical nested path that calls it.

    This is the inverse of `_target_module`: it resolves aliases (eg. `mv-list` /
    `relmv`) so every legacy spelling of a command can be rewritten to its v4 path.
    """
    paths = {}
    for target, path in _canonical_target_paths().items():
        try:
            module_name, function_name = _target_module(target)
        except KeyError:
            continue
        paths.setdefault(f"{module_name}.{function_name}", path)
    return paths


def _legacy_command_paths() -> dict[str, str]:
    canonical_paths = _module_canonical_paths()
    canonical_target_paths = _canonical_target_paths()
    legacy_paths = {}
    for module, aliases in modules.items():
        canonical_path = canonical_paths.get(module)
        if canonical_path is None:
            continue

        function_name = module.rsplit(".", 1)[1]
        legacy_names = {
            function_name,
            function_name.replace("_", "-"),
            function_name.replace("_", ""),
            *_expanded_aliases(module, aliases),
        }
        for legacy_name in legacy_names:
            nested_target = _nested_target([legacy_name])
            nested_path = (
                canonical_target_paths.get(nested_target[0])
                if nested_target is not None and nested_target[1] == 1
                else None
            )
            legacy_paths.setdefault(legacy_name, nested_path or canonical_path)
    return legacy_paths


def canonicalize_usage(text: str) -> str:
    legacy_paths = _legacy_command_paths()
    if not legacy_paths:
        return text

    commands = "|".join(re.escape(command) for command in sorted(legacy_paths, key=len, reverse=True))
    pattern = re.compile(rf"(?<!\w)(library\s+)({commands})(?![\w-])")

    def replace(match: re.Match) -> str:
        legacy_command = match.group(2)
        canonical_command = legacy_paths[legacy_command]
        canonical_suffix = canonical_command.removeprefix(legacy_command)
        remainder = text[match.end() :]
        is_nested_command = any(
            path.startswith(f"{legacy_command} ")
            and remainder.startswith(path.removeprefix(legacy_command))
            for path in _canonical_nested_paths_for_all_groups()
        )
        if (canonical_suffix and remainder.startswith(canonical_suffix)) or is_nested_command:
            return match.group(0)
        return f"{match.group(1)}{canonical_command}"

    return pattern.sub(replace, text)


def _resolve_target(command: str) -> str | None:
    target = command.replace("_", "-")
    if target in _canonical_target_paths():
        return target
    aliases = _module_alias_targets()
    return aliases.get(command) or aliases.get(target)


def _target_module(target: str) -> tuple[str, str]:
    target = _module_alias_targets().get(target, target)
    for module in modules:
        module_name, function_name = module.rsplit(".", 1)
        if function_name.replace("_", "-") == target:
            return module_name, function_name
    raise KeyError(target)


def command_usage(command: str) -> str:
    command = command.replace("_", "-")
    nested_target = _nested_target(command.split())
    target = nested_target[0] if nested_target else _module_alias_targets().get(command, command)
    module_name, function_name = _target_module(target)
    module = importlib.import_module(module_name)

    local_usage = getattr(module, "USAGE", {})
    if function_name in local_usage:
        return local_usage[function_name]

    from library import usage as usage_mod

    usage_value = None
    if function_name in {"listen", "media", "read", "view", "watch"}:
        usage_value = usage_mod.play(function_name)
    elif function_name in {"extensions", "mimetypes", "sizes"}:
        usage_value = usage_mod.disk_usage
    elif function_name in {"merge_cp", "merge_mv", "rel_cp", "rel_mv"}:
        usage_value = usage_mod.merge_mv
    elif function_name == "process_audio":
        usage_value = usage_mod.process_ffmpeg
    else:
        usage_aliases = {
            "hacker_news_add": "hn_add",
            "move_list": "mv_list",
            "optimize_db": "optimize",
            "playback_now": "now",
            "playback_next": "next",
            "playback_seek": "seek",
            "playback_stop": "stop",
            "playback_pause": "pause",
            "pushshift_extract": "pushshift",
            "czkawka_dedupe": "dedupe_czkawka",
        }
        usage_value = getattr(usage_mod, usage_aliases.get(function_name, function_name), "")

    return usage_value if isinstance(usage_value, str) else ""


def canonicalize_usage_for_command(text: str, command: str) -> str:
    text = canonicalize_usage(text)
    if not text:
        return text
    trailing_newline = text.endswith("\n")

    nested_target = _nested_target(command.split())
    target = nested_target[0] if nested_target else _resolve_target(command)
    canonical_command = _canonical_target_paths().get(target, command.replace("_", "-"))

    lines = text.splitlines()
    known_paths = sorted(_canonical_nested_paths_for_all_groups(), key=len, reverse=True)
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("library "):
            continue

        route = next(
            (
                path
                for path in known_paths
                if stripped == f"library {path}" or stripped.startswith(f"library {path} ")
            ),
            None,
        )
        if route is None:
            break
        suffix = stripped[len(f"library {route}") :]
        lines[index] = f"{line[: len(line) - len(stripped)]}library {canonical_command}{suffix}"
        break
    result = "\n".join(lines)
    return result + "\n" if trailing_newline else result


def _invoke_target(target: str):
    module_name, function_name = _target_module(target)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)()


def _dispatch(args) -> None:
    if hasattr(args, "func"):
        subcommand = " ".join(getattr(args, "_nested_path", []))
        if hasattr(args, "_nested_args"):
            if subcommand:
                sys.argv[0] = f"library {subcommand}"
            sys.argv[1:] = args._nested_args
        elif len(sys.argv) >= 2:
            subcommand = sys.argv[1]
            del sys.argv[1]
            # Present flat aliases using their canonical v4 path in help output too
            canonical_path = _canonical_target_paths().get(_resolve_target(subcommand) or "")
            if canonical_path:
                sys.argv[0] = f"library {canonical_path}"
        try:
            return args.func()
        except Exception:
            print("Bug found in", subcommand, " ".join(sys.argv), file=sys.stderr)
            raise

    try:
        log.error("Subcommand %s not found", sys.argv[1])
    except Exception:
        if len(sys.argv) > 1:
            log.error("Invalid args. I see: %s", sys.argv)

    print_help(parser)
    raise SystemExit(1)


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

    def set_func(subparser, module_name: str, function_name: str):
        def import_func():
            module = importlib.import_module(module_name)
            return getattr(module, function_name)()

        subparser.set_defaults(func=import_func)

    def add_parser(subparsers, func, aliases=None):
        # copy so registering aliases never mutates the shared `modules` metadata
        aliases = list(aliases or [])

        module_name, function_name = func.rsplit(".", 1)
        name = function_name.replace("_", "-")

        aliases += [
            s.replace("-", "") for s in [name, *aliases] if "-" in s and s.replace("-", "") not in known_subcommands
        ]
        aliases += [
            s.replace("-", "_") for s in [name, *aliases] if "-" in s and s.replace("-", "_") not in known_subcommands
        ]
        known_subcommands.extend([name, *aliases])

        subp = subparsers.add_parser(name, aliases=aliases, add_help=False)

        set_func(subp, module_name, function_name)
        return subp

    # These flat names collide with a nested resource group and are handled by the
    # nested router; registering them again would create unreachable parsers.
    nested_only_modules = {
        "library.fsdb.filesystem.filesystem",  # `filesystem list`
        "library.mediadb.search.search",  # `captions`
    }

    for module, aliases in modules.items():
        if module in nested_only_modules:
            continue
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

    original_argv = sys.argv[1:]
    if original_argv in (["-h"], ["--help"]):
        print_help(parser)
        raise SystemExit(0)
    if original_argv == ["help"]:
        print_help(parser)
        raise SystemExit(0)

    # `library help <query>` means `library help search <query>` (the v3 spelling)
    if (
        original_argv
        and original_argv[0] == "help"
        and original_argv[1:2] not in ([], ["-h"], ["--help"], ["search"])
    ):
        original_argv = ["help", "search", *original_argv[1:]]

    nested_group = _nested_group(original_argv)
    if (
        original_argv
        and original_argv[-1] in {"-h", "--help"}
        and nested_group is not None
        and isinstance(NESTED_COMMANDS[nested_group], dict)
    ):
        help_node = _nested_tree_node(original_argv[:-1])
        if help_node is not None:
            prefix, node = help_node
            if isinstance(node, dict) and "_target" not in node:
                print(_nested_help(nested_group, prefix=prefix))
                raise SystemExit(0)

    if nested_group and _nested_target(original_argv) is None:
        invalid_path = _invalid_nested_path(nested_group, original_argv)
        print(_nested_help(nested_group, invalid_path))
        raise SystemExit(1)

    if nested_group:
        target_info = _nested_target(original_argv)
        if target_info is not None:
            target, consumed = target_info
            canonical_path = _canonical_target_paths().get(target)
            return _dispatch(
                argparse.Namespace(
                    func=lambda: _invoke_target(target),
                    _nested_path=(canonical_path or " ".join(original_argv[:consumed])).split(),
                    _nested_args=original_argv[consumed:],
                )
            )

    parser.exit_on_error = False  # type: ignore
    try:
        args, _unk = parser.parse_known_args(args)
    except argparse.ArgumentError:
        args = argparse.Namespace(version=False)
    if args.version:
        return print(__version__)

    log.debug("library v%s :: %s", __version__, os.path.realpath(sys.path[0]))
    log.debug(sys.argv)

    return _dispatch(args)


if __name__ == "__main__":
    library()
