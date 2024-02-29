import argparse, json, random, sys, time
from pathlib import Path
from typing import Set
from urllib.parse import urlparse

from xklb import db_media, db_playlists, usage
from xklb.media import av, books
from xklb.scripts import sample_hash
from xklb.scripts.mining import extract_links
from xklb.utils import arg_utils, consts, db_utils, file_utils, iterables, objects, printing, strings, web
from xklb.utils.consts import SC, DBType
from xklb.utils.log_utils import log


def parse_args(**kwargs):
    parser = argparse.ArgumentParser(**kwargs)
    parser.add_argument("--no-extract", "--skip-extract", action="store_true")

    parser.add_argument(
        "--path-include",
        "--include-path",
        "--include",
        "-s",
        nargs="*",
        default=[],
        help="path substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--text-include",
        "--include-text",
        nargs="*",
        default=[],
        help="link text substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--after-include",
        "--include-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--before-include",
        "--include-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--path-exclude",
        "--exclude-path",
        "--exclude",
        "-E",
        nargs="*",
        default=["javascript:", "mailto:", "tel:"],
        help="path substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--text-exclude",
        "--exclude-text",
        nargs="*",
        default=[],
        help="link text substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--after-exclude",
        "--exclude-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--before-exclude",
        "--exclude-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for exclusion (any must match to exclude)",
    )

    parser.add_argument("--strict-include", action="store_true", help="All include args must resolve true")
    parser.add_argument("--strict-exclude", action="store_true", help="All exclude args must resolve true")
    parser.add_argument("--case-sensitive", action="store_true", help="Filter with case sensitivity")
    parser.add_argument(
        "--no-url-decode",
        "--skip-url-decode",
        action="store_true",
        help="Skip URL-decode for --path-include/--path-exclude",
    )

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--audio",
        "-A",
        action="append_const",
        dest="profiles",
        const=DBType.audio,
        help="Create audio database",
    )
    profile.add_argument(
        "--filesystem",
        "--web",
        "-F",
        action="append_const",
        dest="profiles",
        const=DBType.filesystem,
        help="Create filesystem database",
    )
    profile.add_argument(
        "--video",
        "-V",
        action="append_const",
        dest="profiles",
        const=DBType.video,
        help="Create video database",
    )
    profile.add_argument(
        "--text",
        "-T",
        action="append_const",
        dest="profiles",
        const=DBType.text,
        help="Create text database",
    )
    profile.add_argument(
        "--image",
        "-I",
        action="append_const",
        dest="profiles",
        const=DBType.image,
        help="Create image database",
    )
    parser.add_argument("--scan-all-files", "-a", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ext", action=arg_utils.ArgparseList)

    parser.add_argument("--hash", action="store_true")

    parser.add_argument("--cookies", help="path to a Netscape formatted cookies file")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]")

    parser.add_argument("--selenium", action="store_true")
    parser.add_argument("--manual", action="store_true", help="Confirm manually in shell before exiting the browser")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--auto-pager", "--autopager", action="store_true")
    parser.add_argument("--poke", action="store_true")
    parser.add_argument("--chrome", action="store_true")

    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("--local-file", "--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument("--file", "-f", help="File with one URL per line")

    parser.add_argument("database", help=argparse.SUPPRESS)
    if "add" in kwargs["prog"]:
        parser.add_argument("paths", nargs="*", action=arg_utils.ArgparseArgsOrStdin, help=argparse.SUPPRESS)
    args = parser.parse_intermixed_args()

    if not args.profiles:
        args.profiles = [DBType.filesystem]

    if args.scroll:
        args.selenium = True

    if not args.case_sensitive:
        args.before_include = [s.lower() for s in args.before_include]
        args.path_include = [s.lower() for s in args.path_include]
        args.text_include = [s.lower() for s in args.text_include]
        args.after_include = [s.lower() for s in args.after_include]
        args.before_exclude = [s.lower() for s in args.before_exclude]
        args.path_exclude = [s.lower() for s in args.path_exclude]
        args.text_exclude = [s.lower() for s in args.text_exclude]
        args.after_exclude = [s.lower() for s in args.after_exclude]

    if not args.no_url_decode:
        args.path_include = [web.url_decode(s) for s in args.path_include]
        args.path_exclude = [web.url_decode(s) for s in args.path_exclude]

    if hasattr(args, "paths"):
        args.paths = [strings.strip_enclosing_quotes(s) for s in iterables.conform(args.paths)]
    log.info(objects.dict_filter_bool(args.__dict__))

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))
    return args, parser


def consolidate_media(args, path: str) -> dict:
    return {
        "path": path,
        "time_created": consts.APPLICATION_START,
        "time_deleted": 0,
    }


def add_media(args, media):
    if isinstance(media[0], str):
        media = [consolidate_media(args, s) for s in media]

    media = iterables.list_dict_filter_bool(media)
    args.db["media"].insert_all(media, pk="id", alter=True, replace=True)


def spider(args, paths: Set):
    get_urls = iterables.return_unique(extract_links.get_inner_urls)

    new_media_count = 0
    known_paths = set()
    traversed_paths = set()
    while len(paths) > 0:
        new_paths = {}
        path = paths.pop()
        traversed_paths.add(path)
        log.info("Loading %s", path)

        printing.print_overwrite(
            f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]"
        )

        if web.is_index(path):
            for a_ref in get_urls(args, path):
                if a_ref is None:
                    break

                link, link_text = a_ref

                link = web.remove_apache_sorting_params(link)

                if link in (paths | traversed_paths):
                    continue
                if web.is_index(link):
                    if web.is_subpath(path, link):
                        paths.add(link)
                    continue

                if db_media.exists(args, link):
                    known_paths.add(link)
                    continue
                else:
                    new_paths[link] = link_text
        else:
            if path not in (paths | traversed_paths):
                if db_media.exists(args, path):
                    known_paths.add(path)
                else:
                    new_paths[path] = None  # add key to map; title: None

        media = [
            {
                "path": k,
                "title": v,
                "time_created": consts.APPLICATION_START,
                "time_deleted": 0,
            }
            for k, v in new_paths.items()
        ]
        new_media_count += len(media)
        for i, m in enumerate(media, start=1):
            printing.print_overwrite(
                f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]; basic metadata {i} of {len(media)}"
            )

            if DBType.filesystem in args.profiles:
                m |= web.stat(m["path"])
                m["type"] = file_utils.mimetype(m["path"])
            else:
                extension = m["path"].rsplit(".", 1)[-1].lower()
                if (
                    args.scan_all_files
                    or (DBType.video in args.profiles and extension in consts.VIDEO_EXTENSIONS)
                    or (DBType.audio in args.profiles and extension in consts.AUDIO_ONLY_EXTENSIONS)
                    or (DBType.text in args.profiles and extension in consts.TEXTRACT_EXTENSIONS)
                    or (DBType.image in args.profiles and extension in consts.IMAGE_EXTENSIONS)
                ):
                    m |= web.stat(m["path"])

            if getattr(args, "hash", False):
                # TODO: use head_foot_stream
                m["hash"] = sample_hash.sample_hash_file(path)

        for i, m in enumerate(media, start=1):
            printing.print_overwrite(
                f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]; extra metadata {i} of {len(media)}"
            )

            extension = m["path"].rsplit(".", 1)[-1].lower()

            remote_path = m["path"]  # for temp file extraction
            if DBType.video in args.profiles and (extension in consts.VIDEO_EXTENSIONS or args.scan_all_files):
                m |= av.munge_av_tags(args, m["path"])
            if DBType.audio in args.profiles and (extension in consts.AUDIO_ONLY_EXTENSIONS or args.scan_all_files):
                m |= av.munge_av_tags(args, m["path"])
            if DBType.text in args.profiles and (extension in consts.TEXTRACT_EXTENSIONS or args.scan_all_files):
                with web.PartialContent(m["path"]) as temp_file_path:
                    m |= books.munge_book_tags_fast(temp_file_path)
            if DBType.image in args.profiles and (extension in consts.IMAGE_EXTENSIONS or args.scan_all_files):
                with web.PartialContent(m["path"], max_size=32 * 1024) as temp_file_path:
                    m |= books.extract_image_metadata_chunk([{"path": temp_file_path}])[0]
            m["path"] = remote_path  # restore from temp file extraction

        if media:
            add_media(args, media)

        printing.print_overwrite(
            f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]"
        )

    return new_media_count


def add_playlist(args, path):
    info = {
        "hostname": urlparse(path).hostname,
        "extractor_key": "WebFolder",
        "extractor_config": {k: v for k, v in args.__dict__.items() if k not in ["db", "database", "verbose", "paths"]},
        "time_deleted": 0,
    }
    db_playlists.add(args, str(path), info)


def web_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args, _parser = parse_args(prog=f"library {SC.webadd}", usage=usage.webadd)

    if args.no_extract:
        media_new = set()
        media_known = set()
        for p in arg_utils.gen_paths(args):
            if db_media.exists(args, p):
                media_known.add(p)
            else:
                add_media(args, [p])
                media_new.add(p)
            printing.print_overwrite(f"Link import: {len(media_new)} new [{len(media_known)} known]")
    else:
        if args.selenium:
            web.load_selenium(args)
        try:
            for playlist_path in arg_utils.gen_paths(args):
                spider(args, {playlist_path})
                if web.is_index(playlist_path):
                    add_playlist(args, playlist_path)

        finally:
            if args.selenium:
                web.quit_selenium(args)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def web_update(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args, parser = parse_args(prog=f"library {SC.webupdate}", usage=usage.webupdate)

    web_playlists = db_playlists.get_all(
        args,
        sql_filters="extractor_key = 'WebFolder'",
        order_by="""length(path)-length(REPLACE(path, '/', '')) desc
        , random()
        """,
    )

    selenium_needed = any([json.loads(d.get("extractor_config") or "{}").get("selenium") for d in web_playlists])
    if selenium_needed:
        web.load_selenium(args)

    try:
        playlist_count = 0
        for playlist in web_playlists:
            extractor_config = json.loads(playlist.get("extractor_config") or "{}")
            args_env = arg_utils.override_config(parser, extractor_config, args)

            # TODO: use directory Last-Modified header to skip file trees which don't need to be updated
            new_media = spider(args_env, {playlist["path"]})

            if new_media > 0:
                db_playlists.decrease_update_delay(args, playlist["path"])
            else:
                db_playlists.increase_update_delay(args, playlist["path"])

            if playlist_count > 3:
                time.sleep(random.uniform(0.05, 2))
            playlist_count += 1

    finally:
        if selenium_needed:
            web.quit_selenium(args)
