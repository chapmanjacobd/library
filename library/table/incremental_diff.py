import argparse
import json
import math
import pickle
import sqlite3
import uuid
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, consts, file_utils, web
from library.utils.argparse_utils import ArgparseList
from library.utils.log_utils import log
from library.utils.printing import print_df


def parse_args():
    parser = argparse_utils.ArgumentParser(description="Diff two table-like files", usage=usage.incremental_diff)
    parser.add_argument("--mimetype1", "--filetype1")
    parser.add_argument("--encoding1")
    parser.add_argument("--mimetype2", "--filetype2")
    parser.add_argument("--encoding2")
    parser.add_argument("--table1-name", "--table1", "-t1")
    parser.add_argument("--table2-name", "--table2", "-t2")
    parser.add_argument("--table1-index", type=int)
    parser.add_argument("--table2-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--batch-size", "--batch-rows", default=str(consts.DEFAULT_FILE_ROWS_READ_LIMIT))
    parser.add_argument(
        "--join-keys",
        "--id-columns",
        action=ArgparseList,
        help="Comma separated columns that uniquely identify each row",
    )
    parser.add_argument(
        "--join-tables",
        "--concat",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Concat all detected tables",
    )
    parser.add_argument("--transpose", action="store_true", help="Swap X and Y axis. Move columns to rows.")
    parser.add_argument("--sort", "-u")
    arggroups.debug(parser)

    parser.add_argument("path1", help="path to dataset 1")
    parser.add_argument("path2", help="path to dataset 2")
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    if args.batch_size.lower() in ("inf", "none", "all"):
        args.batch_size = None
    else:
        args.batch_size = int(args.batch_size)

    if args.join_keys:
        args.join_keys = [key.strip() for key in args.join_keys if key.strip()]
        if not args.join_keys:
            args.join_keys = None

    return args


def _process_row_chunks(args):
    chunk_start_row = args.start_row
    chunk_end_row = args.batch_size
    while True:
        dfs1 = file_utils.read_file_to_dataframes(
            args.path1,
            table_name=args.table1_name,
            table_index=args.table1_index,
            start_row=chunk_start_row,
            end_row=chunk_end_row,
            order_by=args.sort,
            encoding=args.encoding1,
            mimetype=args.mimetype1,
            join_tables=args.join_tables,
            transpose=args.transpose,
        )
        dfs2 = file_utils.read_file_to_dataframes(
            args.path2,
            table_name=args.table2_name,
            table_index=args.table2_index,
            start_row=chunk_start_row,
            end_row=chunk_end_row,
            order_by=args.sort,
            encoding=args.encoding2,
            mimetype=args.mimetype2,
            join_tables=args.join_tables,
            transpose=args.transpose,
        )

        tables1 = {df.df_name for df in dfs1}
        tables2 = {df.df_name for df in dfs2}
        common_tables = tables1.intersection(tables2)
        dfs1 = sorted(dfs1, key=lambda df: (df.df_name in common_tables, df.df_name), reverse=True)
        dfs2 = sorted(dfs2, key=lambda df: (df.df_name in common_tables, df.df_name), reverse=True)

        empty_dfs = set()
        for df_idx in range(len(dfs1)):
            df1 = dfs1[df_idx].df
            df2 = dfs2[df_idx].df
            df1_name = dfs1[df_idx].df_name
            df2_name = dfs2[df_idx].df_name

            # drop cols with all nulls to allow merging "X" and object columns
            df1 = df1.drop(columns=df1.columns[df1.isnull().all()])
            df2 = df2.drop(columns=df2.columns[df2.isnull().all()])

            if df1.empty and df2.empty:
                empty_dfs.add(df_idx)
                continue
            elif df1.empty:
                log.warning("df1 has no more rows")
            elif df2.empty:
                log.warning("df2 has no more rows")

            df_diff = df1.merge(df2, on=args.join_keys, how="outer", indicator=True)
            df_diff = df_diff[df_diff["_merge"] != "both"]

            if len(df_diff) > 0:
                print(f"## Diff {args.path1}:{df1_name} and {args.path2}:{df2_name}")
                print_df(df_diff)
            del df1
            del df2

        if len(empty_dfs) == len(dfs1):
            break

        del dfs1
        del dfs2

        if args.batch_size:
            if chunk_start_row is None:
                chunk_start_row = 0
            chunk_start_row += args.batch_size
            chunk_end_row += args.batch_size
            log.debug(chunk_end_row)
            continue
        else:
            break


def _stream_kind(path, mimetype):
    if mimetype is None:
        mimetype = file_utils.detect_mimetype(path)
    mimetype = (mimetype or "").strip().lower()
    if mimetype in ("csv", "text/csv"):
        return "csv"
    if mimetype in ("jsonl", "json lines", "geojson lines", "application/x-ndjson"):
        return "jsonl"
    if mimetype in ("json", "application/json"):
        return "json"
    return None


def _input_error(path, detail):
    return ValueError(f"{path}: {detail}")


def _input_type_error(path, detail):
    return TypeError(f"{path}: {detail}")


def _iter_json_array(path, encoding):  # noqa: PLR0912,PLR0915
    decoder = json.JSONDecoder()

    with open(path, encoding=encoding or "utf-8") as stream:
        buffer = ""
        eof = False

        def fill():
            nonlocal buffer, eof
            if not eof:
                chunk = stream.read(64 * 1024)
                if chunk:
                    buffer += chunk
                else:
                    eof = True

        def skip_whitespace():
            nonlocal buffer
            while True:
                stripped = buffer.lstrip()
                if stripped:
                    buffer = stripped
                    return
                if eof:
                    return
                fill()

        skip_whitespace()
        if not buffer:
            raise _input_error(path, "JSON input is empty")

        if buffer[0] != "[":
            try:
                value, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                while not eof:
                    fill()
                    try:
                        value, end = decoder.raw_decode(buffer)
                        break
                    except json.JSONDecodeError:
                        continue
                else:
                    raise _input_error(path, "invalid JSON input")
            if not isinstance(value, dict):
                raise _input_type_error(path, "JSON input must be an array of row objects")
            yield value
            if buffer[end:].strip():
                raise _input_error(path, "JSON input has trailing data")
            return

        buffer = buffer[1:]
        expect_value = True
        while True:
            skip_whitespace()
            if not buffer:
                if eof:
                    raise _input_error(path, "JSON array is not closed")
                fill()
                continue
            if buffer[0] == "]":
                return
            if not expect_value:
                if buffer[0] != ",":
                    raise _input_error(path, "expected ',' between JSON rows")
                buffer = buffer[1:]
                skip_whitespace()
            try:
                value, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if eof:
                    raise _input_error(path, "invalid JSON row") from None
                fill()
                continue
            if not isinstance(value, dict):
                raise _input_type_error(path, "JSON input must be an array of row objects")
            yield value
            buffer = buffer[end:]
            expect_value = False


def _iter_stream_chunks(path, kind, batch_size, encoding, start_row):  # noqa: PLR0912
    import pandas as pd

    if kind == "csv":
        skiprows = range(1, start_row + 1) if start_row else None
        reader = pd.read_csv(
            path,
            chunksize=batch_size,
            skiprows=skiprows,
            encoding=encoding,
        )
        if batch_size is None:
            yield reader
        else:
            yield from reader
        return

    if kind == "jsonl":
        reader = pd.read_json(
            path,
            lines=True,
            chunksize=batch_size,
            encoding=encoding,
        )
        if batch_size is None:
            frames = [reader.iloc[start_row:]] if start_row else [reader]
            yield frames[0]
        else:
            for chunk_index, raw_frame in enumerate(reader):
                frame = raw_frame
                if start_row and (chunk_index + 1) * batch_size <= start_row:
                    continue
                if start_row and chunk_index * batch_size < start_row:
                    frame = frame.iloc[start_row - chunk_index * batch_size :]
                yield frame
        return

    records = _iter_json_array(path, encoding)
    batch = []
    for row_index, record in enumerate(records):
        if row_index < (start_row or 0):
            continue
        batch.append(record)
        if batch_size and len(batch) >= batch_size:
            yield pd.DataFrame.from_records(batch)
            batch = []
    if batch:
        yield pd.DataFrame.from_records(batch)


def _iter_id_frames(args, path, mimetype, encoding, table_name, table_index):
    kind = _stream_kind(path, mimetype)
    if kind:
        yield from _iter_stream_chunks(path, kind, args.batch_size, encoding, args.start_row)
        return

    # Keep ID matching useful for formats without a chunked pandas reader. The
    # common large-file formats take the streaming path above.
    dfs = file_utils.read_file_to_dataframes(
        path,
        table_name=table_name,
        table_index=table_index,
        start_row=args.start_row,
        end_row=None,
        order_by=args.sort,
        encoding=encoding,
        mimetype=mimetype,
        join_tables=args.join_tables,
        transpose=args.transpose,
    )
    yield from (named.df for named in dfs)


def _is_missing(value):
    if value is None:
        return True
    try:
        import pandas as pd

        result = pd.isna(value)
        return isinstance(result, bool) and result
    except (TypeError, ValueError):
        return False


def _normalise_id_value(value):
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except ValueError:
            pass
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (list, tuple)):
        return tuple(_normalise_id_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _normalise_id_value(item)) for key, item in value.items()))
    return value


def _id_token(record, join_keys):
    values = tuple(_normalise_id_value(record[key]) for key in join_keys)
    return pickle.dumps(values, protocol=5), values  # noqa: S301


def _values_equal(left, right):
    if _is_missing(left) and _is_missing(right):
        return True
    if _is_missing(left) or _is_missing(right):
        return False
    try:
        result = left == right
        return bool(result.all()) if hasattr(result, "all") else bool(result)
    except (AttributeError, TypeError, ValueError):
        return False


def _rows_equal(left, right, join_keys):
    columns = (set(left) | set(right)) - set(join_keys)
    return all(_values_equal(left.get(column), right.get(column)) for column in columns)


def _build_id_store(connection, table_name, args, path, mimetype, encoding, source_table_name, source_table_index):
    import pandas as pd

    create_sql = {
        "left_rows": "CREATE TABLE left_rows (id BLOB PRIMARY KEY, row BLOB NOT NULL, seq INTEGER)",
        "right_rows": "CREATE TABLE right_rows (id BLOB PRIMARY KEY, row BLOB NOT NULL, seq INTEGER)",
    }.get(table_name)
    insert_sql = {
        "left_rows": "INSERT INTO left_rows (id, row, seq) VALUES (?, ?, ?)",
        "right_rows": "INSERT INTO right_rows (id, row, seq) VALUES (?, ?, ?)",
    }.get(table_name)
    if create_sql is None or insert_sql is None:
        message = f"Unsupported incremental diff table: {table_name}"
        raise ValueError(message)
    connection.execute(create_sql)
    connection.commit()

    columns = []
    row_number = args.start_row or 0
    for raw_frame in _iter_id_frames(args, path, mimetype, encoding, source_table_name, source_table_index):
        frame = raw_frame
        if not isinstance(frame, pd.DataFrame):
            frame = pd.DataFrame(frame)
        for column in frame.columns:
            if column not in columns:
                columns.append(column)
        missing_columns = [key for key in args.join_keys if key not in frame.columns]
        if missing_columns:
            names = ", ".join(missing_columns)
            raise _input_error(path, f"missing ID column(s): {names}")

        for record in frame.to_dict(orient="records"):
            row_number += 1
            if any(_is_missing(record[key]) for key in args.join_keys):
                raise _input_error(
                    path,
                    f"missing ID value at row {row_number} ({', '.join(args.join_keys)})",
                )
            token, display_id = _id_token(record, args.join_keys)
            try:
                connection.execute(insert_sql, (token, pickle.dumps(record, protocol=5), row_number))  # noqa: S301
            except sqlite3.IntegrityError:
                raise _input_error(path, f"duplicate ID {display_id!r} at row {row_number}") from None
    connection.commit()
    return columns


def _id_diff_frames(connection, args):
    query = """
        SELECT id, left_row, right_row
        FROM (
            SELECT a.id AS id, a.row AS left_row, b.row AS right_row,
                   a.seq AS left_seq, b.seq AS right_seq
            FROM left_rows AS a
            LEFT JOIN right_rows AS b ON a.id = b.id
            UNION ALL
            SELECT b.id AS id, NULL AS left_row, b.row AS right_row,
                   NULL AS left_seq, b.seq AS right_seq
            FROM right_rows AS b
            LEFT JOIN left_rows AS a ON a.id = b.id
            WHERE a.id IS NULL
        )
        ORDER BY COALESCE(left_seq, right_seq)
    """
    cursor = connection.execute(query)
    left_records = []
    right_records = []
    for _token, left_blob, right_blob in cursor:
        left = pickle.loads(left_blob) if left_blob is not None else None  # noqa: S301
        right = pickle.loads(right_blob) if right_blob is not None else None  # noqa: S301
        if left is not None and right is not None and _rows_equal(left, right, args.join_keys):
            continue
        left_records.append(left)
        right_records.append(right)
        if args.batch_size is not None and len(left_records) >= args.batch_size:
            yield left_records, right_records
            left_records = []
            right_records = []
    if left_records:
        yield left_records, right_records


def _print_id_diff(args, left_records, right_records, columns1, columns2):
    import pandas as pd

    left_records_present = [record for record in left_records if record is not None]
    right_records_present = [record for record in right_records if record is not None]
    left_columns = list(dict.fromkeys(columns1 + args.join_keys))
    right_columns = list(dict.fromkeys(columns2 + args.join_keys))
    left_df = pd.DataFrame.from_records(left_records_present, columns=left_columns)
    right_df = pd.DataFrame.from_records(right_records_present, columns=right_columns)
    if left_df.empty:
        left_df = pd.DataFrame(columns=left_columns)
    if right_df.empty:
        right_df = pd.DataFrame(columns=right_columns)
    df_diff = left_df.merge(right_df, on=args.join_keys, how="outer", indicator=True)
    print(f"## Diff {args.path1}:0 and {args.path2}:0")
    print_df(df_diff)


def _process_id_chunks(args):
    if args.join_tables or args.transpose:
        raise ValueError("--join-keys/--id-columns cannot be combined with --join-tables or --transpose")

    spool_path = Path.cwd() / f".library-incremental-diff-{uuid.uuid4().hex}.sqlite3"
    connection = sqlite3.connect(spool_path)
    try:
        columns1 = _build_id_store(
            connection,
            "left_rows",
            args,
            args.path1,
            args.mimetype1,
            args.encoding1,
            args.table1_name,
            args.table1_index,
        )
        columns2 = _build_id_store(
            connection,
            "right_rows",
            args,
            args.path2,
            args.mimetype2,
            args.encoding2,
            args.table2_name,
            args.table2_index,
        )
        for left_records, right_records in _id_diff_frames(connection, args):
            _print_id_diff(args, left_records, right_records, columns1, columns2)
    finally:
        connection.close()
        spool_path.unlink(missing_ok=True)


def process_chunks(args):
    if args.join_keys:
        _process_id_chunks(args)
    else:
        _process_row_chunks(args)


def incremental_diff():
    args = parse_args()
    web.requests_session(args)  # configure session
    process_chunks(args)
