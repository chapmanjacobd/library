import csv, json, os, statistics, sys
from copy import deepcopy
from io import StringIO
from numbers import Number
from pathlib import Path

from library.database.manage import db_history, db_media
from library.play import post_actions
from library.utils import arggroups, consts, db_utils, iterables, nums, printing, processes, sql_utils, strings
from library.utils.consts import SC
from library.utils.log_utils import log

MAX_LOCAL_RESULTS = 50
MAX_MISSING_LOCAL_PATHS = 2


def filter_deleted(media):
    http_list = []
    local_list = []
    nonexistent_local_paths = []

    for i, m in enumerate(media):
        path = m["path"]
        if path.startswith("http"):
            http_list.append(m)
            continue

        if len(local_list) == MAX_LOCAL_RESULTS and len(nonexistent_local_paths) <= MAX_MISSING_LOCAL_PATHS:
            return local_list + http_list + media[i:], nonexistent_local_paths

        if os.path.exists(path):
            local_list.append(m)
        else:
            nonexistent_local_paths.append(path)

    return local_list + http_list, nonexistent_local_paths


def cadence_adjusted_items(args, items: int, time_column=None):
    if time_column:
        history = sql_utils.historical_usage_items(args, freq="daily", time_column=time_column, hide_deleted=True)
    else:
        history = sql_utils.historical_usage(args, freq="daily", hide_deleted=True)

    try:
        historical_daily = statistics.mean((d["count"] or 0) for d in history)
    except statistics.StatisticsError:
        try:
            historical_daily = history[0]["count"]
        except IndexError:
            return None

    if historical_daily <= 1:
        historical_daily = 1.1

    return int(items / historical_daily * 24 * 60 * 60)


def cadence_adjusted_duration(args, duration):
    history = sql_utils.historical_usage(args, freq="hourly", hide_deleted=True)
    try:
        historical_hourly = statistics.mean((d["total_duration"] or 0) for d in history)
    except statistics.StatisticsError:
        try:
            historical_hourly = history[0]["total_duration"]
        except IndexError:
            return None

    if historical_hourly <= 1:
        historical_hourly = 1.1

    return int(duration / historical_hourly * 60 * 60)


def moved_media(args, moved_files: str | list, base_from, base_to) -> int:
    moved_files = iterables.conform(moved_files)
    modified_row_count = 0
    if moved_files:
        df_chunked = iterables.chunks(moved_files, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """UPDATE media
                    SET path=REPLACE(path, ?, ?)
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (base_from, base_to, *chunk_paths),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def should_align_right(k, v):
    if k.endswith(("size", "ratio")) or k.startswith("percent"):
        return True
    if isinstance(v, (int, float)):
        return True
    return None


def _limit_media(args, data, action):
    if not ((args.limit or args.timeout_size) and "path" in data[0].keys() and action in ("media", "filesystem", "listen", "watch")):
        return list(data)

    new_data = []
    moved_count = 0
    for item in data:
        filesize = item.get("size")
        if not filesize and not item["path"].startswith("http"):
            try:
                filesize = os.stat(item["path"]).st_size
            except OSError:
                continue

        if args.timeout_size and processes.sizeout(args.timeout_size, filesize):
            print(f"\nReached sizeout... ({args.timeout_size})", file=sys.stderr)
            break
        if args.limit and args.limit <= moved_count:
            print(f"\nReached limit... ({args.limit})", file=sys.stderr)
            break

        new_data.append(item)
        moved_count += 1
    return new_data


def _delete_media_files(args, media):
    if getattr(args, "delete_files", False):
        if args.simulate:
            log.warning("Would delete %s files", len(media))
        else:
            marked = post_actions.delete_media(args, [d["path"] for d in media])
            log.warning(f"Deleted {marked} files")


def _delete_media_rows(args, media, compact_print_args):
    if getattr(args, "delete_rows", False) or "D" in compact_print_args:
        if args.simulate:
            log.warning("Would delete %s rows", len(media))
        else:
            with args.db.conn:
                for item in media:
                    args.db["media"].delete_where("path = ?", [item["path"]])
            log.warning(f"Deleted {len(media)} rows")


def _mark_deleted_media(args, media, compact_print_args):
    if "r" in compact_print_args:
        if args.simulate:
            log.warning("Would mark metadata records as deleted")
        else:
            marked = db_media.mark_media_deleted(args, [d["path"] for d in media if not Path(d["path"]).exists()])
            log.warning(f"Marked {marked} metadata records as deleted")
    elif getattr(args, "mark_deleted", False) or "d" in compact_print_args:
        if args.simulate:
            log.warning("Would mark %s metadata records as deleted", len(media))
        else:
            marked = db_media.mark_media_deleted(args, [d["path"] for d in media])
            log.warning(f"Marked {marked} metadata records as deleted")


def _mark_watched_media(args, media, compact_print_args):
    if getattr(args, "mark_watched", False) or "w" in compact_print_args:
        if args.simulate:
            log.warning("Would mark %s metadata records as watched", len(media))
        else:
            marked = db_history.add(args, [d["path"] for d in media], mark_done=True)
            log.warning(f"Marked {marked} metadata records as watched")


def _apply_media_actions(args, media, compact_print_args):
    _delete_media_files(args, media)
    _delete_media_rows(args, media, compact_print_args)
    _mark_deleted_media(args, media, compact_print_args)
    _mark_watched_media(args, media, compact_print_args)


def _aggregate_count(media, action):
    if "count" in media[0]:
        return sum(d.get("count") or 0 for d in media)
    if "exists" in media[0]:
        return sum(d.get("exists") or 0 for d in media)
    if action == SC.download_status and "never_attempted" in media[0]:
        return sum(d["never_attempted"] + d["retry_queued"] for d in media)
    return len(media)


def _aggregate_stats(media, aggregate, total_duration, action):
    if "exists" in media[0]:
        aggregate["avg_exists"] = int(nums.safe_mean(m.get("exists") for m in media) or 0)
    if "deleted" in media[0]:
        aggregate["avg_deleted"] = int(nums.safe_mean(m.get("deleted") for m in media) or 0)
    if "duration" in media[0] and action != SC.download_status:
        aggregate["duration"] = total_duration
        aggregate["avg_duration"] = nums.safe_mean(m.get("duration") for m in media)


def _aggregate_cadence(args, aggregate, action, tables, m_columns, total_duration):
    if not (hasattr(args, "action") and "history" in tables and "id" in m_columns):
        return
    if action in (SC.download, SC.download_status) and "time_downloaded" in m_columns:
        aggregate["download_duration"] = cadence_adjusted_items(args, aggregate["count"], time_column="time_downloaded")
    elif total_duration > 0:
        aggregate["cadence_adj_duration"] = cadence_adjusted_duration(args, total_duration)
    else:
        aggregate["cadence_adj_duration"] = cadence_adjusted_items(args, aggregate["count"])


def _aggregate_columns(media, aggregate, cols):
    if "size" in media[0]:
        aggregate["size"] = sum((d.get("size") or 0) for d in media)
        aggregate["avg_size"] = nums.safe_mean(d.get("size") for d in media)
    for column in cols or ():
        if isinstance(media[0][column], Number):
            aggregate[f"sum_{column}"] = sum((d[column] or 0) for d in media)
            aggregate[f"avg_{column}"] = nums.safe_mean(d[column] for d in media)


def _aggregate_media(args, media, action, compact_print_args, tables, m_columns, cols):
    total_duration = sum(nums.safe_int(m.get("duration")) or 0 for m in media)
    if "a" not in compact_print_args or "Aggregate" in media[0].get("path"):
        return media, total_duration

    aggregate = {"path": "Aggregate", "count": _aggregate_count(media, action)}
    _aggregate_stats(media, aggregate, total_duration, action)
    _aggregate_cadence(args, aggregate, action, tables, m_columns, total_duration)
    _aggregate_columns(media, aggregate, cols)
    return [aggregate], total_duration


def _add_download_durations(args, media, action, compact_print_args, tables, m_columns):
    if (
        "a" not in compact_print_args
        and "history" in tables
        and action == SC.download_status
        and "time_downloaded" in m_columns
        and "never_attempted" in media[0]
        and "retry_queued" in media[0]
    ):
        for item in media:
            item["download_duration"] = cadence_adjusted_items(
                args, item["never_attempted"] + item["retry_queued"], time_column="time_downloaded"
            )


def _format_column(media, column, args, action):
    if column.endswith("size"):
        printing.col_filesize(media, column)
    elif column.endswith("duration") or column == "playhead":
        if action in (SC.disk_usage, SC.big_dirs, SC.playlists):
            printing.col_duration_short(media, column)
        else:
            printing.col_duration(media, column)
    elif column.startswith("time_") or "_time_" in column:
        printing.col_naturaltime(media, column)
    elif column == "path" and not getattr(args, "no_url_decode", False):
        printing.col_unquote_url(media, column)
    elif column == "title_path":
        media[:] = [{"title_path": "\n".join(iterables.concat(d["title"], d["path"])), **d} for d in media]
        media[:] = [{k: v for k, v in d.items() if k not in ("title", "path")} for d in media]
    elif column.startswith("percent") or column.endswith("ratio"):
        for item in media:
            item[column] = strings.percent(item[column])


def _format_media_columns(args, media, action):
    for column in set.union(*(set(d.keys()) for d in media)):
        _format_column(media, column, args, action)


def _format_media(args, media, action, compact_print_args, is_template):
    if not any([args.to_json, "f" in compact_print_args, is_template]):
        _format_media_columns(args, media, action)
    if is_template:
        for item in media:
            if item.get("size"):
                item["humansize"] = strings.file_size(item["size"])
            if item.get("path") and not getattr(args, "no_url_decode", False):
                item["humanpath"] = printing.unquote_url(item["path"])
    return iterables.list_dict_filter_bool(media)


def _print_csv_media(args, media, cols):
    if getattr(args, "exists", False):
        media, deleted_paths = filter_deleted(media)
        db_media.mark_media_deleted(args, deleted_paths)
        if len(media) == 0:
            raise FileNotFoundError

    if not cols:
        cols = ["path"]
    if len(cols) == 1:
        printing.pipe_lines(str(d.get(cols[0], "")) + "\n" for d in media)
        return

    selected_cols = [{k: d.get(k, None) for k in cols} for d in media]
    virtual_csv = StringIO()
    csv.DictWriter(virtual_csv, fieldnames=cols).writerows(selected_cols)
    virtual_csv.seek(0)
    for line in virtual_csv.readlines():
        printing.pipe_print(line.strip())


def _print_table_media(args, media, media_len, units, total_duration, compact_print_args):
    total_media = media_len or len(media)
    if args.print_limit:
        media = media[: args.print_limit]
    if sys.stdout.isatty():
        media.reverse()

    tbl = deepcopy(media)
    tbl = [{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in d.items()} for d in tbl]
    max_col_widths = printing.calculate_max_col_widths(tbl)
    adjusted_widths = printing.distribute_excess_width(max_col_widths)
    for column, width in adjusted_widths.items():
        printing.col_resize(tbl, column, width=width)

    colalign = ["right" if should_align_right(k, v) else "left" for k, v in tbl[0].items()]
    printing.table(tbl, colalign=colalign)
    if not units:
        return

    if total_media > 1:
        print(f"{total_media} {units}")
        limit = getattr(args, "limit", None)
        print_limit = getattr(args, "print_limit", None)
        is_limited = limit and int(limit) < total_media
        is_print_limited = print_limit and int(print_limit) < total_media
        if is_limited or is_print_limited:
            limit_warning = ["  (limited by "]
            if is_limited:
                limit_warning.append(f"--limit {limit}")
            if is_print_limited:
                if is_limited:
                    limit_warning.append(" and ")
                limit_warning.append(f"--print-limit {print_limit}")
            limit_warning.append(")")
            print("".join(limit_warning))

    if total_duration > 0:
        total_duration = strings.duration(total_duration)
        if "a" not in compact_print_args:
            print("Total duration:", total_duration)


def _print_media(args, media, print_args, is_template, compact_print_args, cols, media_len, units, total_duration):
    if args.to_json:
        printing.pipe_lines(json.dumps(m) + "\n" for m in media)
    elif is_template:
        for item in media:
            try:
                print(print_args % item)
            except (KeyError, TypeError, ValueError) as exc:
                message = f"Invalid --print template: {print_args}"
                raise ValueError(message) from exc
    elif "f" in compact_print_args:
        _print_csv_media(args, media, cols)
    elif consts.MOBILE_TERMINAL:
        printing.extended_view(media)
    elif "j" in compact_print_args:
        print(json.dumps(media, indent=3))
    elif "c" in compact_print_args:
        printing.write_csv(media)
    elif "n" not in compact_print_args:
        _print_table_media(args, media, media_len, units, total_duration, compact_print_args)


def media_printer(args, data, units: str | None = "media", media_len=None) -> None:
    action = getattr(args, "action", "")
    print_args = getattr(args, "print", "") or ""
    is_template = "%(" in print_args
    compact_print_args = arggroups.get_compact_print_args(args)
    cols = getattr(args, "cols", [])
    m_columns = db_utils.columns(args, "media")

    if not data:
        processes.no_media_found()
    data = _limit_media(args, data, action)
    media = deepcopy(data)
    if args.verbose >= consts.LOG_DEBUG and cols and "*" in cols:
        breakpoint()
    if not media:
        processes.no_media_found()

    try:
        tables = args.db.table_names()
    except AttributeError:
        tables = []

    _apply_media_actions(args, media, compact_print_args)
    media, total_duration = _aggregate_media(args, media, action, compact_print_args, tables, m_columns, cols)
    _add_download_durations(args, media, action, compact_print_args, tables, m_columns)
    media = _format_media(args, media, action, compact_print_args, is_template)
    _print_media(args, media, print_args, is_template, compact_print_args, cols, media_len, units, total_duration)


def printer(args, query, bindings, units=None) -> None:
    media = list(args.db.query(query, bindings))
    try:
        media_printer(args, media, units=units)
    except FileNotFoundError:
        printer(args, query, bindings)  # try again to find a valid file
