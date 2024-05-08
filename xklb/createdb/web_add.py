import concurrent.futures, json, random, sys, time
from urllib.parse import urlparse

from xklb import usage
from xklb.createdb import av, fs_add
from xklb.files import sample_hash
from xklb.mediadb import db_media, db_playlists
from xklb.text import extract_links
from xklb.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    file_utils,
    iterables,
    nums,
    printing,
    sql_utils,
    strings,
    web,
)
from xklb.utils.consts import DBType
from xklb.utils.log_utils import log


def parse_args(action, **kwargs):
    parser = argparse_utils.ArgumentParser(**kwargs)
    arggroups.db_profiles(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)
    arggroups.extractor(parser)

    parser.add_argument("--hash", action="store_true")
    parser.add_argument("--local-html", "--local-file", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument(
        "--sizes",
        action="append",
        help="Only grab extended metadata for files of specific sizes (uses the same syntax as fd-find)",
    )

    arggroups.debug(parser)
    arggroups.database(parser)
    if "add" in action:
        arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    args.action = action

    if not args.profiles:
        args.profiles = [DBType.filesystem]

    if args.sizes:
        args.sizes = sql_utils.parse_human_to_lambda(nums.human_to_bytes, args.sizes)

    if hasattr(args, "paths"):
        args.paths = [strings.strip_enclosing_quotes(s) for s in iterables.conform(args.paths)]

    arggroups.extractor_post(args)
    arggroups.filter_links_post(args)
    arggroups.selenium_post(args)

    arggroups.args_post(args, parser, create_db=action == consts.SC.web_add)
    return args


def consolidate_media(args, path: str) -> dict:
    return {
        "playlists_id": args.playlists_id,
        "time_created": consts.APPLICATION_START,
        "time_deleted": 0,
        "path": path,
    }


def add_media(args, media):
    media = iterables.list_dict_filter_bool(media)
    args.db["media"].insert_all(media, pk="id", alter=True, replace=True)


def add_extra_metadata(args, m):
    extension = m["path"].rsplit(".", 1)[-1].lower()

    remote_path = m["path"]  # for temp file extraction
    if DBType.video in args.profiles and (extension in consts.VIDEO_EXTENSIONS or args.scan_all_files):
        m |= av.munge_av_tags(args, m["path"])
    if DBType.audio in args.profiles and (extension in consts.AUDIO_ONLY_EXTENSIONS or args.scan_all_files):
        m |= av.munge_av_tags(args, m["path"])
    if DBType.text in args.profiles and (extension in consts.TEXTRACT_EXTENSIONS or args.scan_all_files):
        with web.PartialContent(m["path"]) as temp_file_path:
            m |= fs_add.munge_book_tags_fast(temp_file_path)
    if DBType.image in args.profiles and (extension in consts.IMAGE_EXTENSIONS or args.scan_all_files):
        with web.PartialContent(m["path"], max_size=32 * 1024) as temp_file_path:
            m |= fs_add.extract_image_metadata_chunk([{"path": temp_file_path}])[0]
    m["path"] = remote_path  # restore from temp file extraction

    return m


def add_basic_metadata(args, m):
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
        m["hash"] = sample_hash.sample_hash_file(m["path"])

    return m


def spider(args, paths: set):
    original_paths = paths.copy()
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

        if path in original_paths or web.is_index(path) or web.is_html(path):
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

        media = [consolidate_media(args, k) | {"title": v} for k, v in new_paths.items()]
        new_media_count += len(media)

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            gen_media = (f.result() for f in [executor.submit(add_basic_metadata, args, m) for m in media])
            for i, m in enumerate(gen_media):
                media[i] = m
                printing.print_overwrite(
                    f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]; basic metadata {i + 1} of {len(media)}"
                )

        if args.sizes:
            basic_media, extra_media = [], []
            for d in media:
                if d.get("size") is None or args.sizes(d["size"]):
                    extra_media.append(d)
                else:
                    basic_media.append(d)
            if basic_media:
                add_media(args, basic_media)

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            gen_media = (f.result() for f in [executor.submit(add_extra_metadata, args, m) for m in media])
            for i, m in enumerate(gen_media):
                media[i] = m
                printing.print_overwrite(
                    f"Pages to scan {len(paths)} link scan: {new_media_count} new [{len(known_paths)} known]; extra metadata {i + 1} of {len(media)}"
                )

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
        "extractor_config": args.extractor_config,
        "time_deleted": 0,
    }
    return db_playlists.add(args, str(path), info)


def web_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(consts.SC.web_add, usage=usage.web_add)
    web.requests_session(args)  # configure session

    if args.insert_only:
        media_new = set()
        media_known = set()
        for p in arg_utils.gen_paths(args):
            if db_media.exists(args, p):
                media_known.add(p)
            else:
                add_media(args, [consolidate_media(args, p)])
                media_new.add(p)
            printing.print_overwrite(f"Link import: {len(media_new)} new [{len(media_known)} known]")
    else:
        if args.selenium:
            web.load_selenium(args)
        try:
            for playlist_path in arg_utils.gen_paths(args):
                args.playlists_id = add_playlist(args, playlist_path)
                spider(args, {playlist_path})

        finally:
            if args.selenium:
                web.quit_selenium(args)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def web_update(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(consts.SC.web_add, usage=usage.web_update)
    web.requests_session(args)  # configure session

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
            args_env = arg_utils.override_config(args, extractor_config)

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
