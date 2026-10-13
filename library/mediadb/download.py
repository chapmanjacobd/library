import sys

import requests

from library.createdb import gallery_backend, tube_backend
from library.data.http_errors import HTTPStatus
from library.mediadb import db_media, db_playlists
from library.mediafiles import process_ffmpeg, process_image
from library.playback import media_printer
from library.text import extract_links
from library.utils import (
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

USAGE = {
    'download': r"""library database download DATABASE [--prefix /mnt/d/] [--media-type {video,audio,image,filesystem}] [--safe]

    Files are saved to <prefix>/<extractor>/. The default prefix is the current working directory.
    The default download profile is video. `--safe` supports audio, video, and image profiles only.

    By default things download in a random order

        library database download dl.db --prefix ~/output/path/root/

    But you can sort; eg. oldest first

        library database download dl.db -u m.time_modified,m.time_created

    Limit downloads to a specified playlist URLs

        library database filesystem list video.db --to-json --playlists https://www.youtube.com/c/BlenderFoundation/videos | library database download --video video.db --from-json -

    Limit downloads to a specified video URLs or substring

        library database download dl.db --include https://www.youtube.com/watch?v=YE7VzlLtp-4
        library database download dl.db -s https://www.youtube.com/watch?v=YE7VzlLtp-4  # equivalent

    To download files linked within each page, use the pages/url-focused variant. Only links
    within the same domain and parent directory as the seed are followed; other links are
    downloaded but not followed:

        library database download links links.db --recursive --prefix ~/mirror/ https://example.com/docs/

    Download a site's archived pages from the Internet Archive Wayback Machine using the CDX API.
    `--webcache` implies the links profile; add `--recursive` to also parse the archived pages
    for further links:

        library database download links links.db --webcache --prefix ~/mirror/ https://example.com/docs/

    Maximizing the variety of subdomains

        library database download photos.db --photos --image --sort "ROW_NUMBER() OVER ( PARTITION BY SUBSTR(m.path, INSTR(m.path, '//') + 2, INSTR( SUBSTR(m.path, INSTR(m.path, '//') + 2), '/') - 1) )"

    Print list of queued up downloads

        library database download --print

    Print list of saved playlists

        library database playlists dl.db -p a

    Print download queue groups

        library database download status audio.db

    Check videos before downloading

        library play video open_dir.db --online-media-only --loop --exit-code-confirm -i --action ask-keep -m 4  --start 35% --volume=0 -w 'height<720' -E preview

        Assuming you have bound in mpv input.conf a key to 'quit' and another key to 'quit 4',
        using the ask-keep action marks a video as deleted when you 'quit 4' and marks a video as watched when you 'quit'.

        For example, here I bind "'" to "MOVE" and  "j" to "DELETE" when using -k ask_move_or_delete

            ' quit
            j quit 4

        This is pretty intuitive after you use it a few times but another option is to
        define your own post-actions

            `--cmd5 'echo {} >> keep.txt' --cmd6 'echo {} >> rejected.txt'`

        Bind keys in mpv input.conf:

            k quit 5  # goes to keep.txt
            r quit 6  # goes to rejected.txt

    Download checked videos

        library database download --fs open_dir.db --prefix ~/d/dump/video/ -w 'id in (select media_id from history)'
""",
    'download_links': """library database download links DATABASE [URL_OR_PATH ...] [optional args]

    Download the files linked within each page using the filesystem profile. The default
    download profile is filesystem and link extraction is implied, so the given database rows
    (or url/path arguments) are treated as pages whose inner links are downloaded.

    Equivalent to:

        library database download links DATABASE [URL_OR_PATH ...]

    Follow same-domain links recursively:

        library database download links links.db --recursive --prefix ~/mirror/

    Download archived pages from the Internet Archive Wayback Machine using the CDX API.
    `--webcache` extracts links from archived pages; add `--recursive` to also parse them for
    further links:

        library database download links links.db --webcache --prefix ~/mirror/ https://example.com/docs/
""",
}


def parse_args(usage=None, *, links: bool = False):
    parser = argparse_utils.ArgumentParser(usage=usage or USAGE['download'])
    arggroups.sql_fs(parser)

    arggroups.download(parser, direct=True)
    arggroups.download_subtitle(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)
    if links:
        arggroups.spider(parser)

    parser.add_argument("--same-domain", action="store_true", help="Choose a random domain to focus on")

    parser.add_argument("--live", action="store_true", help="Video: Allow live streams to be downloaded")

    parser.add_argument("--small", action="store_true", help="Video: Prefer 480p-like")

    parser.add_argument("--photos", action="store_true", help="Image: Only download JPG and WEBP")
    parser.add_argument("--drawings", action="store_true", help="Image: Only download PNG")
    parser.add_argument("--gifs", action="store_true", help="Image: Only download MP4 and GIFs")

    parser.add_argument("--process", action="store_true", help="Transcode images to AVIF and video/audio to AV1/Opus")
    arggroups.clobber(parser)
    arggroups.process_ffmpeg(parser)
    parser.add_argument("--check-corrupt", "--check-corruption", action="store_true")
    arggroups.media_check(parser)
    parser.set_defaults(same_file_threads=1, full_scan_if_corrupt="7%")
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser, required=False)

    parser.set_defaults(fts=False, direct=not links)
    if links:
        parser.set_defaults(profile=DBType.filesystem)
    args, unk = parser.parse_known_intermixed_args()

    if unk and not args.profile in (DBType.video, DBType.audio):
        parser.error(f"unrecognized arguments: {' '.join(unk)}")

    if args.safe and args.profile == DBType.filesystem:
        parser.error("--safe is supported only with --audio, --video, or --image")

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

    _download(USAGE['download'])


def download_links(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    _download(USAGE['download_links'], links=True)


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
    if args.safe and args.profile == DBType.image:
        gallery_backend.load_module_level_gallery_dl(args)
    for m in media:
        if args.blocklist_rules and sql_utils.is_blocked_dict_like_sql(m, args.blocklist_rules):
            continue

        if args.safe:
            if (args.profile in (DBType.audio, DBType.video) and not tube_backend.is_supported(m["path"])) or (
                args.profile in (DBType.image,) and not gallery_backend.is_supported(m["path"])
            ):
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

            if args.profile in (DBType.audio, DBType.video):
                tube_backend.download(args, m)
            elif args.profile == DBType.image:
                gallery_backend.download(args, m)
            elif args.profile == DBType.filesystem:
                original_path = m["path"]

                dl_paths = [original_path]
                if not args.direct:
                    dl_paths = []
                    try:
                        if args.recursive:
                            link_iter = extract_links.crawl(args, [original_path])
                        else:
                            link_iter = get_inner_urls(args, original_path)
                        for link_dict in link_iter:
                            dl_paths.append(link_dict["link"])
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

                if not dl_paths:
                    log.info("No relevant links in page. Recording download attempt: %s", original_path)
                    db_media.download_add(args, original_path, m, error="No relevant links in page")
                    web.post_download(args)
                    continue

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
            else:
                raise NotImplementedError

        except Exception:
            print("db:", args.database)
            raise
