import sys

from xklb import usage
from xklb.createdb import gallery_backend, tube_backend
from xklb.mediadb import db_media
from xklb.mediafiles import process_ffmpeg, process_image
from xklb.playback import media_printer
from xklb.text import extract_links
from xklb.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    iterables,
    processes,
    sql_utils,
    strings,
    web,
)
from xklb.utils.consts import DBType
from xklb.utils.log_utils import log
from xklb.utils.sqlgroups import construct_download_query


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.download)
    arggroups.sql_fs(parser)

    arggroups.download(parser)
    arggroups.download_subtitle(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)

    parser.add_argument("--same-domain", action="store_true", help="Choose a random domain to focus on")

    parser.add_argument("--live", action="store_true", help="Video: Allow live streams to be downloaded")

    parser.add_argument("--small", action="store_true", help="Video: Prefer 480p-like")

    parser.add_argument("--photos", action="store_true", help="Image: Only download JPG and WEBP")
    parser.add_argument("--drawings", action="store_true", help="Image: Only download PNG")
    parser.add_argument("--gifs", action="store_true", help="Image: Only download MP4 and GIFs")

    parser.add_argument("--links", action="store_true", help="Download media linked within pages")

    parser.add_argument("--process", action="store_true", help="Transcode images to AVIF and video/audio to AV1/Opus")
    arggroups.process_ffmpeg(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)

    parser.set_defaults(paths=None, fts=False)
    args, unk = parser.parse_known_intermixed_args()
    arggroups.args_post(args, parser)

    if unk and not args.profile in (DBType.video, DBType.audio):
        parser.error(f"unrecognized arguments: {' '.join(unk)}")
    args.unk = unk

    if not args.profile and not args.print:
        log.error("Download profile must be specified. Use one of: --video OR --audio OR --image OR --filesystem")
        raise SystemExit(1)

    arggroups.sql_fs_post(args)
    arggroups.filter_links_post(args)
    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)
    arggroups.process_ffmpeg_post(args)
    return args


def download(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args()

    m_columns = db_utils.columns(args, "media")

    if "limit" in args.defaults and "media" in args.db.table_names() and "webpath" in m_columns:
        if args.db.pop("SELECT 1 from media WHERE webpath is NULL and path in (SELECT webpath FROM media) LIMIT 1"):
            with args.db.conn:
                args.db.conn.execute(
                    """
                    DELETE from media WHERE path in (
                        SELECT webpath FROM media
                        WHERE error IS NULL OR error NOT LIKE 'Media check failed%'
                    ) AND webpath is NULL
                    """
                )

    args.blocklist_rules = []
    if "blocklist" in args.db.table_names():
        args.blocklist_rules = [{d["key"]: d["value"]} for d in args.db["blocklist"].rows]

    media = list(arg_utils.gen_d(args))
    if not media:
        query, bindings = construct_download_query(args)
        media = list(args.db.query(query, bindings))

    if not media:
        processes.no_media_found()

    if args.print:
        media_printer.media_printer(args, media)
        return

    get_inner_urls = iterables.return_unique(extract_links.get_inner_urls, lambda d: d["link"])
    for m in media:
        if args.blocklist_rules and sql_utils.is_blocked_dict_like_sql(m, args.blocklist_rules):
            continue

        if args.safe:
            if (args.profile in (DBType.audio, DBType.video) and not tube_backend.is_supported(m["path"])) or (
                args.profile in (DBType.image,) and not gallery_backend.is_supported(args, m["path"])
            ):
                log.info("[%s]: Skipping unsupported URL (safe_mode)", m["path"])
                continue

        # check if download already attempted recently by another process
        previous_time_attempted = m.get("time_modified") or consts.APPLICATION_START  # 0 is nullified
        if not args.force and "time_modified" in m_columns:
            d = args.db.pop_dict(
                f"""
                SELECT time_modified, time_deleted from media m
                WHERE 1=1
                AND path=?
                AND (time_modified > {str(previous_time_attempted)} OR time_deleted > 0)
                """,
                [m["path"]],
            )
            log.debug(d)
            if d:
                if d["time_deleted"]:
                    log.info(
                        "[%s]: Download was marked as deleted %s ago. Skipping!",
                        m["path"],
                        strings.duration(consts.now() - d["time_deleted"]),
                    )
                    continue
                elif d["time_modified"]:
                    log.info(
                        "[%s]: Download already attempted %s ago. Skipping!",
                        m["path"],
                        strings.duration(consts.now() - d["time_modified"]),
                    )
                    continue

        try:  # attempt to download
            log.debug(m)

            if args.profile in (DBType.audio, DBType.video):
                tube_backend.download(args, m)
            elif args.profile == DBType.image:
                gallery_backend.download(args, m)
            elif args.profile == DBType.filesystem:
                original_path = m["path"]

                dl_paths = [original_path]
                if args.links:
                    dl_paths = []
                    for link_dict in get_inner_urls(args, original_path):
                        dl_paths.append(link_dict["link"])

                if not dl_paths:
                    log.info("No relevant links in page. Recording download attempt: %s", original_path)
                    db_media.download_add(args, original_path, error="No relevant links in page")

                any_error = False
                for i, dl_path in enumerate(dl_paths):
                    error = None
                    try:
                        local_path = web.download_url(args, dl_path)
                    except RuntimeError as e:
                        local_path = None
                        error = str(e)

                    if local_path and args.process:
                        extension = local_path.rsplit(".", 1)[-1].lower()
                        if extension in consts.AUDIO_ONLY_EXTENSIONS | consts.VIDEO_EXTENSIONS:
                            result = process_ffmpeg.process_path(args, local_path)
                        elif extension in consts.IMAGE_EXTENSIONS:
                            result = process_image.process_path(args, local_path)

                        if result is not None:
                            local_path = str(result)

                    is_not_found = error is not None and "HTTPNotFound" in error
                    if error is not None and "HTTPNotFound" not in error:
                        any_error = True

                    db_media.download_add(
                        args,
                        original_path,
                        m,
                        local_path,
                        error=error,
                        mark_deleted=is_not_found,
                        delete_webpath_entry=(
                            not any_error if i == len(dl_paths) - 1 else False
                        ),  # only check after last download link was saved
                    )
            else:
                raise NotImplementedError

        except Exception:
            print("db:", args.database)
            raise
