import argparse, os, sqlite3

from library import usage
from library.database.manage import db_playlists
from library.play import media_printer
from library.utils import arggroups, argparse_utils, db_utils
from library.utils.sqlgroups import construct_playlists_query


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.playlists)

    arggroups.sql_fs(parser)

    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")

    parser.set_defaults(fts=False)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)

    return args


def delete_playlists(args, playlists) -> None:
    if args.simulate:
        print(f"Would delete {len(playlists)} playlists")
        return

    deleted_media_count = 0
    try:
        online_media = [p for p in playlists if p.startswith("http")]
        online_playlist_ids = db_playlists.get_ids(args, online_media)
        if online_playlist_ids:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """DELETE from media where
                    playlists_id IN ("""
                    + ",".join(["?"] * len(online_playlist_ids))
                    + ")",
                    (*online_playlist_ids,),
                )
                deleted_media_count += cursor.rowcount
    except sqlite3.OperationalError:  # no such column: playlists_id
        pass

    deleted_playlist_count = 0
    with args.db.conn:
        playlist_paths = playlists + [p.rstrip(os.sep) for p in playlists]
        playlist_ids = db_playlists.get_ids(args, playlist_paths)
        if playlist_ids:
            cursor = args.db.conn.execute(
                "delete from playlists where id in (" + ",".join(["?"] * len(playlist_ids)) + ")",
                playlist_ids,
            )
            deleted_playlist_count = cursor.rowcount

    local_media = [p.rstrip(os.sep) for p in playlists if not p.startswith("http")]
    for folder in local_media:
        with args.db.conn:
            cursor = args.db.conn.execute("delete from media where path like ?", (folder + "%",))
            deleted_media_count += cursor.rowcount

    print(f"Deleted {deleted_playlist_count} playlists ({deleted_media_count} media records)")


_PLAYLIST_FILTER_ARGS = (
    "include",
    "exclude",
    "where",
    "ext",
    "sizes",
    "bitrates",
    "local_media_only",
    "online_media_only",
    "time_created",
    "created_within",
    "created_before",
    "time_modified",
    "modified_within",
    "modified_before",
    "time_deleted",
    "deleted_within",
    "deleted_before",
    "downloaded_within",
    "downloaded_before",
    "keep_dir",
    "no_video",
    "no_audio",
    "subtitles",
    "no_subtitles",
    "duration",
    "duration_from_size",
)


def _playlists_filtered(args) -> bool:
    """Whether the playlist query is narrowed beyond the default deleted filter."""
    return any(getattr(args, arg, None) for arg in _PLAYLIST_FILTER_ARGS)


def playlists() -> None:
    args = parse_args()

    pl_columns = db_utils.columns(args, "playlists")
    m_columns = db_utils.columns(args, "media")
    query, bindings = construct_playlists_query(args)

    if "playlists_id" in m_columns:
        # `Playlist-less media` is only meaningful for an unfiltered listing. When
        # searching/filtering, keep just the media belonging to matching playlists.
        join = "JOIN" if _playlists_filtered(args) else "LEFT JOIN"
        query = f"""
        select
            coalesce(p.path, "Playlist-less media") path
            {', p.extractor_key' if 'extractor_key' in pl_columns else ", 'Playlist-less media' as extractor_key"}
            {', p.title' if 'title' in pl_columns else ''}
            {', p.time_deleted' if 'time_deleted' in pl_columns else ''}
            {', count(*) FILTER(WHERE play_count>0) play_count' if 'play_count' in m_columns else ''}
            {', sum(m.duration) duration' if 'duration' in m_columns else ''}
            {', sum(m.size) size' if 'size' in m_columns else ''}
            , count(*) count
        from media m
        {join} ({query}) p on p.id = m.playlists_id
        group by m.playlists_id, coalesce(p.path, "Playlist-less media")
        order by count, p.path
        """

    if "a" in arggroups.get_compact_print_args(args):
        query = f"""
        select
            'Aggregate of playlists' path
            {', count(*) FILTER(WHERE time_deleted>0) deleted_count' if 'time_deleted' in query else ''}
            {', sum(play_count) play_count' if 'play_count' in query else ''}
            {', sum(duration) duration' if 'duration' in query else ''}
            {', avg(duration) avg_playlist_duration' if 'duration' in query else ''}
            {', sum(size) size' if 'size' in query else ''}
            , count(*) playlists_count
            {', sum(count) media_count' if 'count' in query else ''}
        from ({query})
        """

    playlists = list(args.db.query(query, bindings))
    media_printer.media_printer(args, playlists, units="playlists")

    if args.mark_deleted:
        deleted_count = db_playlists.mark_media_deleted(args, [d["path"] for d in playlists])
        if deleted_count > 0:
            print("Marked", deleted_count, "playlists as deleted")

    if args.delete_rows:
        delete_playlists(args, [d["path"] for d in playlists])
