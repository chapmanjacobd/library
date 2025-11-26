import concurrent.futures, os, statistics
from contextlib import suppress
from pathlib import Path

from library import usage
from library.mediadb import db_media, db_playlists
from library.utils import arggroups, argparse_utils, consts, db_utils, file_utils, iterables, nums, objects, printing
from library.utils.file_utils import trash
from library.utils.log_utils import log
from library.utils.path_utils import tld_from_url


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_add)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Add metadata for paths even if the info_hash already exists in the media table",
    )
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser, create_db=True)
    return args


def get_tracker_domain(torrent):
    trackers = torrent.trackers()
    trackers = [t for t in trackers]
    if not trackers:
        return torrent.source

    announce_urls = []
    for t in sorted(trackers, key=lambda t: (t.source, t.tier)):
        try:
            if url := t.url:
                announce_urls.append(url)
        except UnicodeDecodeError:
            continue
    log.debug(announce_urls)

    for tracker in iterables.flatten(announce_urls):
        domain = tld_from_url(tracker)
        if domain:
            return domain

    return torrent.source


def torrent_decode(path):
    import libtorrent as lt

    limits = {
        "max_buffer_size": 55_000_000,  # max .torrent size in bytes
        "max_pieces": 2_000_000,
        "max_decode_tokens": 5_000_000,  # max tokens in bdecode
    }

    torrent = lt.torrent_info(str(path), limits)  # type: ignore
    metadata = lt.bdecode(torrent.metadata())  # type: ignore

    torrent.private = bool(metadata.get(b"private"))

    src = metadata.get(b"source")
    torrent.source = os.fsdecode(src) if src else None

    return torrent


def _extract_metadata(path):
    ltt = torrent_decode(path)
    assert ltt.num_files() > 0

    files = [{"path": f.path, "size": f.size, "time_deleted": 0} for f in ltt.files()]
    file_sizes = [f["size"] for f in files]

    stat = os.stat(path, follow_symlinks=False)

    web_seeds = []
    for ws in ltt.web_seeds():
        with suppress(Exception):
            url = ws["url"]
            if url:
                web_seeds.append(url)

    return {
        "path": path,
        "title": ltt.name(),
        "tracker": get_tracker_domain(ltt),
        "time_uploaded": nums.safe_int(ltt.creation_date()),
        "time_created": int(stat.st_ctime),
        "time_modified": int(stat.st_mtime) or consts.now(),
        "time_deleted": 0,
        "time_downloaded": 0,
        "size": sum(file_sizes),
        "size_avg": statistics.mean(file_sizes),
        "size_median": statistics.median(file_sizes),
        "file_count": len(files),
        "src": ltt.source,
        "is_private": ltt.private,
        "comment": ltt.comment(),
        "author": ltt.creator(),
        "info_hash": str(ltt.info_hash()),
        "web_seeds": web_seeds,
        "files": files,
    }


def extract_metadata(path):
    try:
        return _extract_metadata(path)
    except Exception:
        log.error("[%s]: corrupt or empty torrent", path)
        raise


def torrents_add():
    args = parse_args()

    db_playlists.create(args)
    db_media.create(args)

    scanned_set = set(file_utils.gen_paths(args, default_exts=(".torrent",)))

    known_hashes = set()
    try:
        pl_columns = db_utils.columns(args, "playlists")

        known_hashes = {d["info_hash"] for d in args.db.query("select info_hash from playlists")}

        existing_set = {
            d["path"]
            for d in args.db.query(
                f"""select path from playlists
                where 1=1
                    {'AND coalesce(time_deleted, 0)=0' if 'time_deleted' in pl_columns else ''}
                """,
            )
        }
    except Exception as excinfo:
        log.debug(excinfo)
        paths = list(scanned_set)
    else:
        paths = list(scanned_set - existing_set)

        deleted_files = list(existing_set - scanned_set)
        if len(list(scanned_set)) >= 1 and len(deleted_files) >= 1:
            deleted_files = [p for p in deleted_files if not Path(p).exists()]
            deleted_count = db_playlists.mark_media_deleted(args, deleted_files)
            if deleted_count > 0:
                print("Marked", deleted_count, "orphaned metadata records as deleted")

    num_paths = len(paths)
    start_time = consts.now()
    with concurrent.futures.ThreadPoolExecutor() as ex:
        futures = [ex.submit(extract_metadata, path) for path in paths]

        for idx, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                torrent_info = future.result()
            except Exception:
                log.exception(idx)
                if args.verbose >= consts.LOG_DEBUG:
                    raise
            else:
                if torrent_info["info_hash"] in known_hashes and not args.force:
                    if args.delete_files:
                        log.info("[%s]: known info_hash; Deleting.", torrent_info["path"])
                        trash(args, torrent_info["path"])
                    else:
                        log.info(
                            "[%s]: Skipping known info_hash %s. Use --force to override",
                            torrent_info["path"],
                            torrent_info["info_hash"],
                        )
                    continue
                known_hashes.add(torrent_info["info_hash"])

                percent = (idx + 1) / num_paths * 100
                eta = printing.eta(idx + 1, num_paths, start_time=start_time) if num_paths > 2 else ""
                printing.print_overwrite(
                    f"[{torrent_info['path']}] Extracting metadata {idx + 1} of {num_paths} ({percent:3.1f}%) {eta}",
                    flush=True,
                )

                files = torrent_info.pop("files")
                log.debug(torrent_info)
                torrent_info["webpath"] = iterables.safe_unpack(
                    sorted(torrent_info.pop("web_seeds"), key=len, reverse=True)
                )

                playlists_id = db_playlists._add(args, objects.dict_filter_bool(torrent_info))
                files = [file | {"playlists_id": playlists_id} for file in files]
                args.db["media"].insert_all(files, pk=["playlists_id", "path"], alter=True, replace=True)
    print("Extracted metadata from", num_paths, "files")

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)
