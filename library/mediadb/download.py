import sys

import requests

from library import usage as usage_mod
from library.createdb import gallery_backend, tube_backend
from library.data.http_errors import HTTPStatus
from library.mediadb import db_media, db_playlists
from library.mediafiles import process_ffmpeg, process_image
from library.playback import media_printer
from library.text import extract_links
from library.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    iterables,
    processes,
    shell_utils,
    sql_utils,
    strings,
    web,
)
from library.utils.consts import DBType
from library.utils.log_utils import log
from library.utils.sqlgroups import construct_download_query


def parse_args(usage=None, *, links: bool = False):
    parser = argparse_utils.ArgumentParser(usage=usage or usage_mod.download)
    arggroups.sql_fs(parser)

    arggroups.download(parser, direct=True)
    arggroups.download_subtitle(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)
    arggroups.spider(parser)

    parser.add_argument("--same-domain", action="store_true", help="Choose a random domain to focus on")

    arggroups.download_media_filters(parser)

    parser.add_argument("--process", action="store_true", help="Transcode images to AVIF and video/audio to AV1/Opus")
    arggroups.clobber(parser)
    arggroups.process_ffmpeg(parser)
    parser.add_argument("--check-corrupt", "--check-corruption", action="store_true")
    arggroups.media_check(parser)
    parser.set_defaults(same_file_threads=1, full_scan_if_corrupt="7%")
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser, required=False)

    parser.set_defaults(fts=False)
    args, unk = parser.parse_known_intermixed_args()

    args.extract_links = links or args.recursive or args.webcache

    if unk and not args.profile in (DBType.video, DBType.audio, DBType.auto):
        parser.error(f"unrecognized arguments: {' '.join(unk)}")

    validate_safe(args, parser, extracts_links=args.extract_links)

    arggroups.args_post(args, parser, create_db=args.database and args.database.endswith(consts.SQLITE_EXTENSIONS))
    args.unk = unk

    arggroups.sql_fs_post(args)
    arggroups.filter_links_post(args)
    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)
    arggroups.process_ffmpeg_post(args)
    return args


def download(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    _download(usage_mod.download)


def download_links(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    _download(usage_mod.download_links, links=True)


def validate_safe(args, parser, *, extracts_links: bool) -> None:
    """Reject unusable `--safe` combinations and note the limits of link-extraction `--safe`."""
    if getattr(args, "safe", False) and (
        getattr(args, "direct", False) or getattr(args, "profile", None) in (DBType.filesystem, DBType.text)
    ):
        parser.error(
            "--safe is supported only with --auto, --audio, --video, or --image"
            " (not --direct or --media-type filesystem/text)"
        )
    if getattr(args, "safe", False) and extracts_links:
        log.warning(
            "--safe cannot be fully enforced when extracting links from pages; "
            "only the extracted links are checked against known domains"
        )


def resolve_download_profile(args, path) -> str:
    """Resolve the `auto` download profile to a concrete media type for a URL.

    `auto` prefers the built-in downloader for direct media links: only gallery-dl's
    *site* extractors count as `image` here, so a bare `…/pic.png` falls back to
    `filesystem`/built-in. gallery-dl is an optional dependency; when it is missing,
    `auto` falls back to yt-dlp and the built-in downloader instead of failing.
    """
    if tube_backend.is_supported(path):
        return DBType.video
    if gallery_backend.ensure_configured(args) and gallery_backend.is_supported(path):
        return DBType.image
    return DBType.filesystem


def route_links(args, m, original_path, link_paths, backend_args_cache, builtin_fn, *, safe_links=False) -> None:
    """Download `link_paths`, choosing a backend per link (see `resolve_download_profile`).

    `--direct` or a filesystem/text profile hands the whole batch to the built-in
    downloader so `_download_builtin` can decide whether the seed page row is removable.
    Under `auto` the built-in links are likewise collected and handed over as one batch,
    because dispatching them one at a time would let `_download_builtin` delete the seed
    page row (and record failures) as soon as any single link succeeded; yt-dlp/gallery-dl
    links are dispatched one at a time. `builtin_fn` is called with
    `builtin_fn(args, m, original_path, link_paths)`.
    """
    if getattr(args, "direct", False) or args.profile in (DBType.filesystem, DBType.text):
        builtin_fn(args, m, original_path, link_paths)
        return

    builtin_paths = []
    for link_path in link_paths:
        if safe_links and not safe_supported(args, link_path):
            log.info("Skipping unsupported URL (safe_mode) %s", link_path)
            continue

        profile = args.profile
        if profile == DBType.auto:
            profile = resolve_download_profile(args, link_path)
        if profile == args.profile:
            backend_args = args
        else:
            backend_args = backend_args_cache.get(profile)
            if backend_args is None:
                backend_args = backend_args_cache[profile] = arg_utils.args_override(args, {"profile": profile})

        if profile in (DBType.audio, DBType.video):
            tube_backend.download(backend_args, m | {"path": link_path})
        elif profile == DBType.image:
            gallery_backend.download(backend_args, m | {"path": link_path})
        else:  # filesystem, or an unexpected resolved profile
            builtin_paths.append(link_path)

    if builtin_paths:
        builtin_fn(args, m, original_path, builtin_paths)


def safe_supported(args, path) -> bool:
    """Whether `--safe` should allow downloading `path` with the active profile.

    `--safe` is only accepted with a media-type profile (see `validate_safe`), so
    filesystem/text are intentionally not considered here. Direct/generic URLs are
    rejected for every profile: `is_supported` excludes gallery-dl's catch-all
    extractors, and `auto` falls back to the built-in downloader for such links.
    """
    if args.profile == DBType.auto:
        return resolve_download_profile(args, path) != DBType.filesystem
    if args.profile in (DBType.audio, DBType.video):
        return tube_backend.is_supported(path)
    if args.profile == DBType.image:
        # Load gallery-dl lazily so DB-less link-download commands work without a pre-load.
        if not gallery_backend.ensure_configured(args):
            return False
        return gallery_backend.is_supported(path)
    return True


def _download(usage, *, links: bool = False) -> None:
    args = parse_args(usage, links=links)

    if not args.simulate:
        db_playlists.create(args)
        db_media.create(args)

    m_columns = db_utils.columns(args, "media")

    if "limit" in args.defaults and "media" in args.db.table_names() and "webpath" in m_columns:
        if args.db.pop("SELECT 1 from media WHERE webpath is NULL and path in (SELECT webpath FROM media) LIMIT 1"):
            if not args.simulate:
                with args.db.conn:
                    args.db.conn.execute(
                        """
                        DELETE from media WHERE path in (
                            SELECT webpath FROM media
                            WHERE error IS NULL OR error NOT LIKE 'Media check failed%'
                        ) AND webpath IS NULL
                        """
                    )

    args.blocklist_rules = []
    if "blocklist" in args.db.table_names():
        args.blocklist_rules = [{d["key"]: d["value"]} for d in args.db["blocklist"].rows]

    media = list(shell_utils.gen_d(args))
    if not media:
        query, bindings = construct_download_query(args)
        media = list(args.db.query(query, bindings))

    if not media:
        processes.no_media_found()

    if args.print:
        media_printer.media_printer(args, media)
        return
    if args.simulate:
        print("Would download:", *(m["path"] for m in media), sep="\n")
        return

    get_inner_urls = iterables.return_unique(extract_links.iter_links, lambda d: d["link"])
    backend_args_cache = {}
    for m in media:
        if args.blocklist_rules and sql_utils.is_blocked_dict_like_sql(m, args.blocklist_rules):
            continue

        if args.safe and not args.extract_links and not safe_supported(args, m["path"]):
            log.info("Skipping unsupported URL (safe_mode) %s", m["path"])
            continue

        # check if download already attempted recently by another process
        previous_time_attempted = m.get("time_modified") or consts.APPLICATION_START  # 0 is nullified
        if not args.force and "time_modified" in m_columns:
            d = args.db.pop_dict(
                f"""
                SELECT
                    time_modified
                    , time_deleted
                    {", download_attempts" if 'download_attempts' in m_columns else ', 0 as download_attempts'}
                FROM media
                WHERE path=?
                """,
                [m["path"]],
            )
            log.debug(d)
            if d:
                if d["time_deleted"]:
                    log.info(
                        "Download was marked as deleted %s ago. Skipping %s",
                        strings.duration(consts.now() - d["time_deleted"]),
                        m["path"],
                    )
                    continue
                elif d.get("time_modified") and d["time_modified"] > int(previous_time_attempted):
                    log.info(
                        "Download already attempted %s ago. Skipping %s",
                        strings.duration(consts.now() - d["time_modified"]),
                        m["path"],
                    )
                    continue
                elif d.get("download_attempts") and d["download_attempts"] >= args.download_retries:
                    log.info("Download attempts exceed download retries limit. Skipping %s", m["path"])
                    continue

        try:  # attempt to download
            log.debug(m)

            original_path = m["path"]

            if args.extract_links:
                link_paths = []
                try:
                    if args.recursive:
                        link_iter = extract_links.crawl(args, [original_path])
                    else:
                        link_iter = get_inner_urls(args, original_path)
                    for link_dict in link_iter:
                        link_paths.append(link_dict["link"])
                except requests.HTTPError as excinfo:
                    log.warning(
                        "HTTPError %s. Recording download attempt: %s", excinfo.response.status_code, original_path
                    )
                    db_media.download_add(
                        args,
                        webpath=original_path,
                        info=m,
                        error=str(excinfo),
                        mark_deleted=excinfo.response.status_code == HTTPStatus.NOT_FOUND,
                        delete_webpath_entry=False,
                    )
                    web.post_download(args)
                    continue

                if not link_paths:
                    log.info("No relevant links in page. Recording download attempt: %s", original_path)
                    db_media.download_add(args, original_path, m, error="No relevant links in page")
                    web.post_download(args)
                    continue
            else:
                link_paths = [original_path]

            route_links(
                args,
                m,
                original_path,
                link_paths,
                backend_args_cache,
                _download_builtin,
                safe_links=args.safe and args.extract_links,
            )

        except Exception:
            print("db:", args.database)
            raise


def _download_builtin(args, m, original_path, dl_paths) -> None:
    """Download each path with the built-in downloader, recording results against original_path."""
    any_error = False
    for i, dl_path in enumerate(dl_paths):
        error = None
        try:
            local_path = web.download_link(args, dl_path)
        except RuntimeError as excinfo:
            local_path = None
            error = str(excinfo)

        local_paths = [local_path]
        if local_path and args.process:
            result = None
            extension = local_path.rsplit(".", 1)[-1].lower()
            if extension in consts.AUDIO_ONLY_EXTENSIONS | consts.VIDEO_EXTENSIONS:
                result = process_ffmpeg.process_path(args, local_path)
            elif extension in consts.IMAGE_EXTENSIONS:
                result = process_image.process_path(args, local_path)

            if result is not None:
                local_paths = process_ffmpeg.result_paths(result)

        is_not_found = error is not None and "HTTPNotFound" in error
        if error is not None and "HTTPNotFound" not in error:
            any_error = True

        for output_index, local_path in enumerate(local_paths):
            db_media.download_add(
                args,
                webpath=original_path,
                info=m,
                local_path=local_path,
                error=error,
                mark_deleted=is_not_found,
                delete_webpath_entry=(
                    not any_error
                    if i == len(dl_paths) - 1 and output_index == len(local_paths) - 1
                    else False
                ),  # only check after last downloaded output was saved
            )
