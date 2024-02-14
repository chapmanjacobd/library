import csv, json, os, shlex, statistics
from copy import deepcopy
from io import StringIO
from numbers import Number
from pathlib import Path
from typing import Union

from tabulate import tabulate

from xklb import db_media, history
from xklb.utils import consts, iterables, printing, processes, sql_utils, strings
from xklb.utils.consts import SC
from xklb.utils.log_utils import log


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

    return int(duration / historical_hourly * 60 * 60)


def moved_media(args, moved_files: Union[str, list], base_from, base_to) -> int:
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


def media_printer(args, data, units=None, media_len=None) -> None:
    if units is None:
        units = "media"

    action = getattr(args, "action", "")
    print_args = getattr(args, "print", "")
    cols = getattr(args, "cols", [])

    media = deepcopy(data)

    if args.verbose >= consts.LOG_DEBUG and cols and "*" in cols:
        breakpoint()

    if not media:
        processes.no_media_found()

    if "f" not in print_args and "limit" in getattr(args, "defaults", []):
        media.reverse()

    duration = sum(m.get("duration") or 0 for m in media)
    if "a" in print_args and ("Aggregate" not in media[0].get("path") or ""):
        if "count" in media[0]:
            D = {"path": "Aggregate", "count": sum(d.get("count") or 0 for d in media)}
        elif action == SC.download_status and "never_downloaded" in media[0]:
            potential_downloads = sum(d["never_downloaded"] + d["retry_queued"] for d in media)
            D = {"path": "Aggregate", "count": potential_downloads}
        else:
            D = {"path": "Aggregate", "count": len(media)}

        if "duration" in media[0] and action not in (SC.download_status):
            D["duration"] = duration
            D["avg_duration"] = duration / len(media)

        if hasattr(args, "action"):
            if action in (SC.download, SC.download_status):
                D["download_duration"] = cadence_adjusted_items(args, D["count"], time_column="time_downloaded")
            else:
                if duration > 0:
                    D["cadence_adj_duration"] = cadence_adjusted_duration(args, duration)
                else:
                    D["cadence_adj_duration"] = cadence_adjusted_items(args, D["count"])

        if "size" in media[0]:
            D["size"] = sum((d.get("size") or 0) for d in media)
            D["avg_size"] = sum((d.get("size") or 0) for d in media) / len(media)

        if cols:
            for c in cols:
                if isinstance(media[0][c], Number):
                    D[f"sum_{c}"] = sum((d[c] or 0) for d in media)
                    D[f"avg_{c}"] = sum((d[c] or 0) for d in media) / len(media)
        media = [D]

    else:
        if "r" in print_args:
            marked = db_media.mark_media_deleted(args, [d["path"] for d in media if not Path(d["path"]).exists()])
            log.warning(f"Marked {marked} metadata records as deleted")
        elif "d" in print_args:
            marked = db_media.mark_media_deleted(args, [d["path"] for d in media])
            log.warning(f"Marked {marked} metadata records as deleted")

        if "w" in print_args:
            marked = history.add(args, [d["path"] for d in media])
            log.warning(f"Marked {marked} metadata records as watched")

    if "a" not in print_args and action == SC.download_status:
        for m in media:
            m["download_duration"] = cadence_adjusted_items(
                args, m["never_downloaded"] + m["retry_queued"], time_column="time_downloaded"
            )  # TODO where= p.extractor_key, or try to use SQL

    for k, v in list(media[0].items()):
        if k.endswith("size"):
            printing.col_naturalsize(media, k)
        elif k.endswith("duration") or k in ("playhead",):
            printing.col_duration(media, k)
        elif k.startswith("time_") or "_time_" in k:
            printing.col_naturaltime(media, k)
        elif k == "title_path":
            media = [{"title_path": "\n".join(iterables.concat(d["title"], d["path"])), **d} for d in media]
            media = [{k: v for k, v in d.items() if k not in ("title", "path")} for d in media]
        elif k.startswith("percent") or k.endswith("ratio"):
            for d in media:
                d[k] = strings.safe_percent(d[k])
        # elif isinstance(v, (int, float)):
        #     for d in media:
        #         if d[k] is not None:
        #             d[k] = f'{d[k]:n}'  # TODO add locale comma separators

    def should_align_right(k, v):
        if k.endswith(("size", "ratio")) or k.startswith("percent"):
            return True
        if isinstance(v, (int, float)):
            return True
        return None

    media = iterables.list_dict_filter_bool(media)

    if "f" in print_args:
        if len(media) <= 1000 and getattr(args, "action", "") not in [consts.SC.open_links]:
            media, deleted_paths = filter_deleted(media)
            db_media.mark_media_deleted(args, deleted_paths)
            if len(media) == 0:
                raise FileNotFoundError

        if not cols:
            cols = ["path"]

        selected_cols = [{k: d.get(k, None) for k in cols} for d in media]
        virtual_csv = StringIO()
        wr = csv.writer(virtual_csv, quoting=csv.QUOTE_NONE)
        wr = csv.DictWriter(virtual_csv, fieldnames=cols)
        wr.writerows(selected_cols)

        virtual_csv.seek(0)
        if getattr(args, "moved", False):
            for line in virtual_csv.readlines():
                printing.pipe_print(line.strip().replace(args.moved[0], "", 1))
            moved_media(args, [d["path"] for d in media], *args.moved)
        else:
            for line in virtual_csv.readlines():
                printing.pipe_print(line.strip())

    elif "j" in print_args or consts.MOBILE_TERMINAL:
        print(json.dumps(media, indent=3))
    elif "c" in print_args:
        printing.write_csv_to_stdout(media)
    else:
        tbl = deepcopy(media)
        tbl = [{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in d.items()} for d in tbl]
        max_col_widths = printing.calculate_max_col_widths(tbl)
        adjusted_widths = printing.distribute_excess_width(max_col_widths)
        for k, v in adjusted_widths.items():
            printing.col_resize(tbl, k, v)

        colalign = ["right" if should_align_right(k, v) else "left" for k, v in tbl[0].items()]
        print(tabulate(tbl, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False, colalign=colalign))

        if len(media) > 1:
            print(
                f"{media_len or len(media)} {units}"
                + (f" (limited by --limit {args.limit})" if args.limit and int(args.limit) <= len(media) else ""),
            )

        if duration > 0:
            duration = printing.human_duration(duration)
            if "a" not in print_args:
                print("Total duration:", duration)


def printer(args, query, bindings, units=None) -> None:
    media = list(args.db.query(query, bindings))
    try:
        media_printer(args, media, units=units)
    except FileNotFoundError:
        printer(args, query, bindings)  # try again to find a valid file
