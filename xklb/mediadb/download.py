import argparse, os, sys

from xklb import media_printer, usage
from xklb.createdb import gallery_backend, tube_backend
from xklb.mediadb import db_media
from xklb.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    iterables,
    printing,
    processes,
    sql_utils,
    web,
)
from xklb.utils.consts import SC, DBType
from xklb.utils.log_utils import log
from xklb.utils.sqlgroups import construct_download_query


def parse_args():
    parser = argparse_utils.ArgumentParser(
        prog="library download",
        usage=usage.download,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arggroups.sql_fs(parser)

    arggroups.download(parser)
    arggroups.download_subtitle(parser)
    arggroups.requests(parser)

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--audio",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Use audio downloader",
    )
    profile.add_argument(
        "--video",
        action="store_const",
        dest="profile",
        const=DBType.video,
        help="Use video downloader",
    )
    profile.add_argument(
        "--image",
        "--photo",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help="Use image downloader",
    )
    profile.add_argument(
        "--filesystem",
        "--fs",
        "--web",
        action="store_const",
        dest="profile",
        const=DBType.filesystem,
        help="Use filesystem downloader",
    )

    parser.add_argument("--same-domain", action="store_true", help="Choose a random domain to focus on")

    parser.add_argument("--prefix", default=os.getcwd(), help=argparse.SUPPRESS)

    parser.add_argument("--small", action="store_true", help="Video: Prefer 480p-like")

    parser.add_argument("--photos", action="store_true", help="Image: Download JPG and WEBP")
    parser.add_argument("--drawings", action="store_true", help="Image: Download PNG")
    parser.add_argument("--gifs", action="store_true", help="Image: Download MP4 and GIFs")
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)
    parser.set_defaults(paths=None)

    args, unk = parser.parse_known_intermixed_args()
    args.action = SC.download
    arggroups.args_post(args, parser)

    if unk and not args.profile in (DBType.video, DBType.audio):
        parser.error(f"unrecognized arguments: {' '.join(unk)}")
    args.unk = unk

    if not args.profile and not args.print:
        log.error("Download profile must be specified. Use one of: --video OR --audio OR --image OR --filesystem")
        raise SystemExit(1)

    arggroups.sql_fs_post(args)
    return args


def process_downloadqueue(args) -> list[dict]:
    query, bindings = construct_download_query(args)
    if args.print:
        media_printer.printer(args, query, bindings)
        return []

    media = list(args.db.query(query, bindings))
    if not media:
        processes.no_media_found()
    return media


def mark_download_attempt(args, paths) -> int:
    paths = iterables.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = iterables.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""update media
                    set time_modified={consts.now()}
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def dl_download(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args()
    m_columns = db_utils.columns(args, "media")

    if "limit" in args.defaults and "media" in args.db.table_names() and "webpath" in m_columns:
        if args.db.pop("SELECT 1 from media WHERE webpath is NULL and path in (select webpath from media) LIMIT 1"):
            with args.db.conn:
                args.db.conn.execute(
                    """
                    DELETE from media WHERE webpath is NULL
                    AND path in (
                        select webpath from media
                        WHERE error IS NULL OR error != 'Media check failed'
                    )
                    """
                )

    args.blocklist_rules = []
    if "blocklist" in args.db.table_names():
        args.blocklist_rules = [{d["key"]: d["value"]} for d in args.db["blocklist"].rows]

    if args.profile == DBType.filesystem:
        web.requests_session(args)  # prepare requests session

    media = list(arg_utils.gen_d(args))
    if not media:
        media = process_downloadqueue(args)

    for m in media:
        if args.blocklist_rules and sql_utils.is_blocked_dict_like_sql(m, args.blocklist_rules):
            mark_download_attempt(args, [m["path"]])
            continue

        if args.safe:
            if (args.profile in (DBType.audio, DBType.video) and not tube_backend.is_supported(m["path"])) or (
                args.profile in (DBType.image) and not gallery_backend.is_supported(args, m["path"])
            ):
                log.info("[%s]: Skipping unsupported URL (safe_mode)", m["path"])
                mark_download_attempt(args, [m["path"]])
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
                        "[%s]: Download marked deleted (%s ago). Skipping!",
                        m["path"],
                        printing.human_duration(consts.now() - d["time_deleted"]),
                    )
                    mark_download_attempt(args, [m["path"]])
                    continue
                elif d["time_modified"]:
                    log.info(
                        "[%s]: Download already attempted recently (%s ago). Skipping!",
                        m["path"],
                        printing.human_duration(consts.now() - d["time_modified"]),
                    )
                    continue

        try:
            log.debug(m)

            if args.profile in (DBType.audio, DBType.video):
                tube_backend.download(args, m)
            elif args.profile == DBType.image:
                gallery_backend.download(args, m)
            elif args.profile == DBType.filesystem:
                local_path = web.download_url(m["path"], output_prefix=args.prefix)
                db_media.download_add(args, m["path"], m, local_path)
            else:
                raise NotImplementedError
        except Exception:
            print("db:", args.database)
            raise
