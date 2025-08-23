import csv, json, os, shlex, statistics, sys
from copy import deepcopy
from io import StringIO
from numbers import Number
from pathlib import Path

from library.mediadb import db_history, db_media
from library.playback import post_actions
from library.utils import consts, db_utils, iterables, nums, printing, processes, sql_utils, strings
from library.utils.consts import SC
from library.utils.log_utils import log


def filter_deleted(media):
    http_list = []
    local_list = []
    nonexistent_local_paths = []

    for i, m in enumerate(media):
        path = m["path"]
        if path.startswith("http"):
            http_list.append(m)
            continue

        if len(local_list) == 50 and len(nonexistent_local_paths) <= 2:
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

    if historical_hourly == 0:
        return None

    return int(duration / historical_hourly * 60 * 60)


def moved_media(args, moved_files: str | list, base_from, base_to) -> int:
    moved_files = iterables.conform(moved_files)
    modified_row_count = 0
    if moved_files:
        df_chunked = iterables.chunks(moved_files, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""UPDATE media
                    SET path=REPLACE(path, '{shlex.quote(base_from)}', '{shlex.quote(base_to)}')
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def should_align_right(k, v):
    if k.endswith(("size", "ratio")) or k.startswith("percent"):
        return True
    if isinstance(v, (int, float)):
        return True
    return None


def media_printer(args, data, units: str | None = "media", media_len=None) -> None:
    action = getattr(args, "action", "")
    print_args = getattr(args, "print", "")
    cols = getattr(args, "cols", [])
    m_columns = db_utils.columns(args, "media")

    media = deepcopy(data)

    if args.verbose >= consts.LOG_DEBUG and cols and "*" in cols:
        breakpoint()

    if not media:
        processes.no_media_found()

    try:
        tables = args.db.table_names()
    except AttributeError:
        tables = []

    if getattr(args, "delete_files", False):
        marked = post_actions.delete_media(args, [d["path"] for d in media])
        log.warning(f"Deleted {marked} files")

    if getattr(args, "delete_rows", False) or "D" in print_args:
        with args.db.conn:
            for d in media:
                args.db["media"].delete_where("path = ?", [d["path"]])
        log.warning(f"Deleted {len(media)} rows")

    if "r" in print_args:
        marked = db_media.mark_media_deleted(args, [d["path"] for d in media if not Path(d["path"]).exists()])
        log.warning(f"Marked {marked} metadata records as deleted")
    elif getattr(args, "mark_deleted", False) or "d" in print_args:
        marked = db_media.mark_media_deleted(args, [d["path"] for d in media])
        log.warning(f"Marked {marked} metadata records as deleted")

    if getattr(args, "mark_watched", False) or "w" in print_args:
        marked = db_history.add(args, [d["path"] for d in media], mark_done=True)
        log.warning(f"Marked {marked} metadata records as watched")

    total_duration = sum(nums.safe_int(m.get("duration")) or 0 for m in media)
    if "a" in print_args and ("Aggregate" not in media[0].get("path") or ""):
        if "count" in media[0]:
            D = {"path": "Aggregate", "count": sum(d.get("count") or 0 for d in media)}
        elif "exists" in media[0]:
            D = {"path": "Aggregate", "count": sum(d.get("exists") or 0 for d in media)}
        elif action == SC.download_status and "never_attempted" in media[0]:
            potential_downloads = sum(d["never_attempted"] + d["retry_queued"] for d in media)
            D = {"path": "Aggregate", "count": potential_downloads}
        else:
            D = {"path": "Aggregate", "count": len(media)}

        if "exists" in media[0]:
            D["avg_exists"] = int(nums.safe_mean(m.get("exists") for m in media) or 0)
        if "deleted" in media[0]:
            D["avg_deleted"] = int(nums.safe_mean(m.get("deleted") for m in media) or 0)

        if "duration" in media[0] and action not in (SC.download_status,):
            D["duration"] = total_duration
            D["avg_duration"] = nums.safe_mean(m.get("duration") for m in media)

        if hasattr(args, "action") and "history" in tables and "id" in m_columns:
            if action in (SC.download, SC.download_status) and "time_downloaded" in m_columns:
                D["download_duration"] = cadence_adjusted_items(args, D["count"], time_column="time_downloaded")
            elif total_duration > 0:
                D["cadence_adj_duration"] = cadence_adjusted_duration(args, total_duration)
            else:
                D["cadence_adj_duration"] = cadence_adjusted_items(args, D["count"])

        if "size" in media[0]:
            D["size"] = sum((d.get("size") or 0) for d in media)
            D["avg_size"] = nums.safe_mean(d.get("size") for d in media)

        if cols:
            for c in cols:
                if isinstance(media[0][c], Number):
                    D[f"sum_{c}"] = sum((d[c] or 0) for d in media)
                    D[f"avg_{c}"] = nums.safe_mean(d[c] for d in media)
        media = [D]

    if (
        "a" not in print_args
        and "history" in tables
        and action == SC.download_status
        and "time_downloaded" in m_columns
    ):
        for m in media:
            m["download_duration"] = cadence_adjusted_items(
                args, m["never_attempted"] + m["retry_queued"], time_column="time_downloaded"
            )  # TODO where= p.extractor_key, or try to use SQL

    if not any([args.to_json, "f" in print_args]):
        for k in set.union(*(set(d.keys()) for d in media)):
            if k.endswith("size"):
                printing.col_filesize(media, k)
            elif k.endswith("duration") or k in ("playhead",):
                if action in (SC.disk_usage, SC.big_dirs, SC.playlists):
                    printing.col_duration_short(media, k)
                else:
                    printing.col_duration(media, k)
            elif k.startswith("time_") or "_time_" in k:
                printing.col_naturaltime(media, k)
            elif k == "path" and not getattr(args, "no_url_decode", False):
                printing.col_unquote_url(media, k)
            elif k == "title_path":
                media = [{"title_path": "\n".join(iterables.concat(d["title"], d["path"])), **d} for d in media]
                media = [{k: v for k, v in d.items() if k not in ("title", "path")} for d in media]
            elif k.startswith("percent") or k.endswith("ratio"):
                for d in media:
                    d[k] = strings.percent(d[k])

    media = iterables.list_dict_filter_bool(media)

    if args.to_json:
        printing.pipe_lines(json.dumps(m) + "\n" for m in media)

    elif "f" in print_args:
        if getattr(args, "exists", False):
            media, deleted_paths = filter_deleted(media)
            db_media.mark_media_deleted(args, deleted_paths)
            if len(media) == 0:
                raise FileNotFoundError

        if not cols:
            cols = ["path"]

        if len(cols) == 1:
            printing.pipe_lines(str(d.get(cols[0], "")) + "\n" for d in media)
        else:
            selected_cols = [{k: d.get(k, None) for k in cols} for d in media]
            virtual_csv = StringIO()
            wr = csv.writer(virtual_csv, quoting=csv.QUOTE_NONE)
            wr = csv.DictWriter(virtual_csv, fieldnames=cols)
            wr.writerows(selected_cols)

            virtual_csv.seek(0)
            for line in virtual_csv.readlines():
                printing.pipe_print(line.strip())

    elif consts.MOBILE_TERMINAL:
        printing.extended_view(media)
    elif "j" in print_args:
        print(json.dumps(media, indent=3))
    elif "c" in print_args:
        printing.write_csv_to_stdout(media)
    elif "n" in print_args:
        pass
    else:
        total_media = media_len or len(media)
        if args.print_limit:
            media = media[: args.print_limit]

        if sys.stdout.isatty():
            media.reverse()  # long lists are usually read in reverse unless in a PAGER

        tbl = deepcopy(media)
        tbl = [{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in d.items()} for d in tbl]
        max_col_widths = printing.calculate_max_col_widths(tbl)
        adjusted_widths = printing.distribute_excess_width(max_col_widths)
        for k, v in adjusted_widths.items():
            printing.col_resize(tbl, k, width=v)

        colalign = ["right" if should_align_right(k, v) else "left" for k, v in tbl[0].items()]
        printing.table(tbl, colalign=colalign)

        if units:
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
                if "a" not in print_args:
                    print("Total duration:", total_duration)


def printer(args, query, bindings, units=None) -> None:
    media = list(args.db.query(query, bindings))
    try:
        media_printer(args, media, units=units)
    except FileNotFoundError:
        printer(args, query, bindings)  # try again to find a valid file
