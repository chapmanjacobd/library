import concurrent.futures
import json
import random
import re
import sys
import time
from contextlib import suppress
from urllib.parse import urlparse

import requests

from library import usage
from library.database.add import av, fs_add_metadata
from library.file import sample_hash
from library.database.manage import db_media, db_playlists
from library.links import extract_links
from library.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    file_utils,
    iterables,
    nums,
    objects,
    printing,
    shell_utils,
    sql_utils,
    strings,
    web,
)

from library.utils.consts import DBType
from library.utils.log_utils import log

PLAYLIST_DELAY_THRESHOLD = 3

HTML_SIZE_RE = re.compile(
    r"(?<![\w.])(?P<size>\d+(?:\.\d+)?\s*(?:bytes?|[kmgtpe](?:i?b)?|b))\s*$",
    re.IGNORECASE,
)
HTML_BYTES_RE = re.compile(r"(?<!\S)(?P<size>\d+)\s*$")


def parse_args(action, **kwargs):
    parser = argparse_utils.ArgumentParser(**kwargs)
    arggroups.db_profiles(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)
    arggroups.extractor(parser)
    parser.set_defaults(threads=4)

    parser.add_argument(
        "--media",
        "--no-html",
        action="store_true",
        help="Scan given links as media directly instead of parsing as web pages",
    )
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--hash", action="store_true")
    parser.add_argument(
        "--sizes",
        "--size",
        "-S",
        action="append",
        help="""Only grab extended metadata for files of specific sizes (uses the same syntax as fd-find)
-S 6           # 6 MB exactly (not likely)
-S-6           # less than 6 MB
-S+6           # more than 6 MB
-S 6%%10       # 6 MB ±10 percent (between 5 and 7 MB)
-S+5GB -S-7GB  # between 5 and 7 GB""",
    )

    arggroups.debug(parser)
    arggroups.database(parser)
    if "add" in action:
        arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=action == consts.SC.web_add)

    if args.sizes:
        args.sizes = sql_utils.parse_human_to_lambda(nums.human_to_bytes, args.sizes)

    if hasattr(args, "paths"):
        args.paths = [strings.strip_enclosing_quotes(s) for s in iterables.conform(args.paths)]

    arggroups.extractor_post(args)
    arggroups.filter_links_post(args)
    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)

    if not args.profiles and args.sizes:
        args.profiles = [DBType.filesystem]
    args.profiles = arggroups.resolve_profiles(action, args.profiles)
    arggroups.warn_missing_profile_deps(args.profiles)

    return args


def consolidate_media(args, path: str) -> dict:
    d = {
        "time_created": consts.APPLICATION_START,
        "time_deleted": 0,
        "path": path,
    }
    if getattr(args, "playlists_id", None):
        d["playlists_id"] = args.playlists_id
    return d


def add_media(args, media):
    for m in media:
        db_media.add(args, m)


def add_extra_metadata(args, m):
    extension = m["path"].rsplit(".", 1)[-1].lower()

    remote_path = m["path"]  # for temp file extraction
    if DBType.video in args.profiles and (extension in consts.VIDEO_EXTENSIONS or args.scan_all_files):
        m = av.munge_av_tags(args, m)
    if DBType.audio in args.profiles and extension in consts.AUDIO_ONLY_EXTENSIONS:
        m = av.munge_av_tags(args, m)
    if DBType.text in args.profiles and arggroups.text_profile_available() and (
        extension in consts.TEXTRACT_EXTENSIONS or args.scan_all_files
    ):
        with web.PartialContent(m["path"]) as temp_file_path:
            m |= fs_add_metadata.munge_book_tags_fast(temp_file_path)
    if DBType.image in args.profiles and arggroups.image_profile_available() and (
        extension in consts.IMAGE_EXTENSIONS or args.scan_all_files
    ):
        with web.PartialContent(m["path"], max_size=32 * 1024) as temp_file_path:
            m |= fs_add_metadata.extract_image_metadata_chunk([{"path": temp_file_path}])[0]
    m["path"] = remote_path  # restore from temp file extraction

    web.sleep(args)

    return m


def add_basic_metadata(args, m):
    if DBType.filesystem in args.profiles:
        with suppress(TimeoutError):
            try:
                web_stats = web.stat(m["path"])
                if web_stats:
                    if web_stats.st_size:
                        m["size"] = web_stats.st_size
                    m["time_modified"] = web_stats.st_mtime
            except FileNotFoundError:
                m["time_deleted"] = consts.now()
        with suppress(TimeoutError):
            m["type"] = file_utils.detect_mimetype(m["path"])

    if getattr(args, "hash", False):
        # TODO: use head_foot_stream
        m["hash"] = sample_hash.sample_hash_file(m["path"])

    web.sleep(args)
    return m


def extract_html_size(m) -> int | None:
    after_text = m.get("after_text")
    if not after_text:
        return None

    match = HTML_SIZE_RE.search(after_text)
    if match:
        return nums.human_to_bytes(match.group("size"))

    match = HTML_BYTES_RE.search(after_text)
    return int(match.group("size")) if match else None


def _scan_html_path(args, path, paths, traversed_paths, known_paths, new_paths):
    try:
        link_dicts = list(iterables.return_unique(extract_links.get_inner_urls, lambda d: d.values())(args, path))
    except requests.HTTPError as excinfo:
        log.error(excinfo)
        return

    log.debug("%s urls found in %s", len(link_dicts), path)
    random.shuffle(link_dicts)
    for link_dict in link_dicts:
        link = web.remove_apache_sorting_params(link_dict.pop("link"))
        if link in traversed_paths or link in paths:
            continue
        if db_media.exists(args, link):
            known_paths.add(link)
        elif web.is_subpath(path, link) and web.is_html(args, link):
            log.info("queueing sub-page %s", link)
            paths.append(link)
        else:
            new_paths[link] = objects.merge_dict_values_str(new_paths.get(link) or {}, link_dict)


def _discover_spider_paths(args, path, paths, original_paths, known_paths, traversed_paths):
    new_paths = {}
    traversed_paths.add(path)
    if args.media:
        paths.append(path)
        for _ in range(args.threads * 5):
            if paths:
                queued_path = paths.pop()
                if args.force:
                    new_paths[queued_path] = None
                elif db_media.exists(args, queued_path):
                    known_paths.add(queued_path)
                else:
                    new_paths[queued_path] = None
    elif path in original_paths or web.is_index(path) or web.is_html(args, path):
        _scan_html_path(args, path, paths, traversed_paths, known_paths, new_paths)
    elif path in traversed_paths or path in paths:
        pass
    elif db_media.exists(args, path):
        known_paths.add(path)
    else:
        new_paths[path] = None
    return new_paths


def _enrich_media(args, media, paths, new_media_count, known_count, operation, label):
    enriched_media = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=1 if args.verbose >= consts.LOG_DEBUG else args.threads
    ) as executor:
        gen_media = (f.result() for f in [executor.submit(operation, args, m) for m in media])
        for i, media_entry in enumerate(gen_media):
            enriched_media.append(media_entry)
            printing.print_overwrite(
                f"Pages to scan {len(paths)} link scan: {new_media_count} new [{known_count} known]; "
                f"{label} metadata {i + 1} of {len(media)}"
            )
    return enriched_media


def _enrich_spider_media(args, media, paths, new_media_count, known_count):
    if DBType.filesystem in args.profiles or args.hash:
        media = _enrich_media(args, media, paths, new_media_count, known_count, add_basic_metadata, "basic")
        add_media(args, media)

    if args.sizes:
        media = [d for d in media if d.get("size") is None or args.sizes(d["size"])]

    media = _enrich_media(args, media, paths, new_media_count, known_count, add_extra_metadata, "extra")
    if media:
        add_media(args, media)


def spider(args, paths: list):
    original_paths = set(paths)

    new_media_count = 0
    known_paths = set()
    traversed_paths = set()
    while len(paths) > 0:
        path = paths.pop()
        log.info("Loading %s", path)

        printing.print_overwrite(
            f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]"
        )

        new_paths = _discover_spider_paths(args, path, paths, original_paths, known_paths, traversed_paths)

        media = [consolidate_media(args, k) | (v or {}) for k, v in new_paths.items()]
        for m in media:
            html_size = extract_html_size(m)
            if html_size is not None:
                m["size"] = html_size
        new_media_count += len(media)

        _enrich_spider_media(args, media, paths, new_media_count, len(known_paths))

        printing.print_overwrite(
            f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]"
        )

    return new_media_count


def add_playlist(args, path):
    info = {
        "hostname": urlparse(path).hostname,
        "extractor_key": "WebFolder",
        "extractor_config": args.extractor_config,
        "time_deleted": 0,
    }
    return db_playlists.add(args, str(path), info)


def _web_add_without_extract(args):
    media_new = set()
    media_known = set()
    for path in shell_utils.gen_paths(args):
        if db_media.exists(args, path):
            media_known.add(path)
        else:
            add_media(args, [consolidate_media(args, path)])
            media_new.add(path)
        printing.print_overwrite(f"Link import: {len(media_new)} new [{len(media_known)} known]")
    print()


def _web_add_spider(args):
    if args.selenium:
        web.load_selenium(args)
    try:
        if args.media:
            spider(args, list(shell_utils.gen_paths(args)))
        else:
            for playlist_path in shell_utils.gen_paths(args):
                args.playlists_id = add_playlist(args, playlist_path)
                spider(args, [playlist_path])
    finally:
        if args.selenium:
            web.quit_selenium(args)


def web_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(consts.SC.web_add, usage=usage.web_add)

    db_playlists.create(args)
    db_media.create(args)

    if args.no_extract:
        _web_add_without_extract(args)
    else:
        _web_add_spider(args)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def web_update(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(consts.SC.web_update, usage=usage.web_update)

    web_playlists = db_playlists.get_all(
        args,
        sql_filters=["AND extractor_key = 'WebFolder'"],
        order_by="""length(path)-length(REPLACE(path, '/', '')) desc
        , random()
        """,
    )

    selenium_needed = any(json.loads(d.get("extractor_config") or "{}").get("selenium") for d in web_playlists)
    if selenium_needed:
        web.load_selenium(args)

    try:
        for playlist_count, playlist in enumerate(web_playlists):
            extractor_config = json.loads(playlist.get("extractor_config") or "{}")
            args_env = arg_utils.override_config(args, extractor_config)

            # TODO: use directory Last-Modified header to skip file trees which don't need to be updated
            new_media = spider(args_env, [playlist["path"]])

            if new_media > 0:
                db_playlists.update_more_frequently(args, playlist["path"], extractor_config)
            else:
                db_playlists.update_less_frequently(args, playlist["path"], extractor_config)

            if playlist_count > PLAYLIST_DELAY_THRESHOLD:
                time.sleep(random.uniform(0.05, 2))

    finally:
        if selenium_needed:
            web.quit_selenium(args)
