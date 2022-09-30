from random import random
from typing import Tuple

from xklb import db, play_actions
from xklb.utils import DEFAULT_PLAY_QUEUE, SC

audio_include_string = (
    lambda x: f"""and (
    path like :include{x}
    OR mood like :include{x}
    OR genre like :include{x}
    OR year like :include{x}
    OR bpm like :include{x}
    OR key like :include{x}
    OR time like :include{x}
    OR decade like :include{x}
    OR categories like :include{x}
    OR city like :include{x}
    OR country like :include{x}
    OR description like :include{x}
    OR album like :include{x}
    OR title like :include{x}
    OR artist like :include{x}
)"""
)

audio_exclude_string = (
    lambda x: f"""and (
    path not like :exclude{x}
    AND mood not like :exclude{x}
    AND genre not like :exclude{x}
    AND year not like :exclude{x}
    AND bpm not like :exclude{x}
    AND key not like :exclude{x}
    AND time not like :exclude{x}
    AND decade not like :exclude{x}
    AND categories not like :exclude{x}
    AND city not like :exclude{x}
    AND country not like :exclude{x}
    AND description not like :exclude{x}
    AND album not like :exclude{x}
    AND title not like :exclude{x}
    AND artist not like :exclude{x}
)"""
)

video_include_string = (
    lambda x: f"""and (
    path like :include{x}
    OR tags like :include{x}
)"""
)

video_exclude_string = (
    lambda x: f"""and (
    path not like :exclude{x}
    AND tags not like :exclude{x}
)"""
)

other_include_string = lambda x: f"and path like :include{x}"
other_exclude_string = lambda x: f"and path not like :exclude{x}"


def search_substring(args, cf, bindings) -> None:
    if args.action == SC.watch:
        play_actions.construct_search_bindings(args, bindings, cf, video_include_string, video_exclude_string)
    elif args.action == SC.listen:
        play_actions.construct_search_bindings(args, bindings, cf, audio_include_string, audio_exclude_string)
    else:  # args.action == SC.filesystem
        play_actions.construct_search_bindings(args, bindings, cf, other_include_string, other_exclude_string)


def construct_query(args) -> Tuple[str, dict]:
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    args.table = "media"
    if args.db["media"].detect_fts():
        if args.include:
            args.table = db.fts_search(args, bindings)
        elif args.exclude:
            search_substring(args, cf, bindings)
    else:
        search_substring(args, cf, bindings)

    if args.table == "media" and not args.print:
        limit = 60_000
        if args.random:
            if args.include:
                args.sort = "random(), " + args.sort
            else:
                limit = DEFAULT_PLAY_QUEUE * 16
        cf.append(f"and rowid in (select rowid from media order by random() limit {limit})")

    args.sql_filter = " ".join(cf)
    args.sql_filter_bindings = bindings

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    # switching between videos with and without subs is annoying
    subtitle_count = ">0"
    if random() < 0.659:  # bias slightly toward videos without subtitles
        subtitle_count = "=0"

    query = f"""SELECT path
        , size
        {', duration' if args.action in (SC.listen, SC.watch) else ''}
        {', cast(length(tags) / 4.2 / 220 * 60 as INT) + 10 duration' if args.action == SC.read else ''}
        {', subtitle_count' if args.action == SC.watch else ''}
        {', sparseness' if args.action == SC.filesystem else ''}
        {', is_dir' if args.action == SC.filesystem else ''}
        {', ' + ', '.join(args.cols) if args.cols and args.cols != ['duration'] else ''}
    FROM {args.table}
    WHERE 1=1
        {args.sql_filter}
        {f'and path not like "%{args.keep_dir}%"' if args.post_action == 'askkeep' else ''}
        {'and time_deleted=0' if args.action in (SC.listen, SC.watch) and 'time_deleted' not in args.sql_filter else ''}
        {'and time_downloaded > 0' if args.action in (SC.listen, SC.watch) and 'time_downloaded' not in args.sql_filter else ''}
    ORDER BY 1=1
        {', video_count > 0 desc' if args.action == SC.watch else ''}
        {', audio_count > 0 desc' if args.action == SC.listen else ''}
        {', width < height desc' if args.portrait else ''}
        {f', subtitle_count {subtitle_count} desc' if args.action == SC.watch and not any([args.print, 'subtitle_count' in args.where]) else ''}
        {', ' + args.sort if args.sort else ''}
        , random()
    {LIMIT} {OFFSET}
    """

    return query, bindings


def watch() -> None:
    args = play_actions.parse_args(SC.watch, "video.db", default_chromecast="Living Room TV")
    play_actions.process_playqueue(args, construct_query)


def listen() -> None:
    args = play_actions.parse_args(SC.listen, "audio.db", default_chromecast="Xylo and Orchestra")
    play_actions.process_playqueue(args, construct_query)


def filesystem() -> None:
    args = play_actions.parse_args(SC.filesystem, "fs.db")
    play_actions.process_playqueue(args, construct_query)


def read() -> None:
    args = play_actions.parse_args(SC.read, "text.db")
    play_actions.process_playqueue(args, construct_query)


def view() -> None:
    args = play_actions.parse_args(SC.view, "image.db")
    play_actions.process_playqueue(args, construct_query)
