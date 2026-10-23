import errno, mimetypes, os
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import wraps
from io import StringIO
from pathlib import Path
from typing import NamedTuple

import urllib3

from library.utils import consts, processes, web
from library.utils.log_utils import log
from itertools import starmap

MIN_DETECTION_COHERENCE = 0.8


def is_file_open(path):
    if os.name == "nt":
        try:
            os.open(path, os.O_RDWR | os.O_EXCL)
            return False
        except OSError:
            return True
    else:
        open_files = set()
        for proc in os.listdir("/proc"):
            try:
                fd_dir = os.path.join("/proc", proc, "fd")
                for fd in os.listdir(fd_dir):
                    link = os.readlink(os.path.join(fd_dir, fd))
                    if link.startswith("/") and link == path:
                        open_files.add(link)
            except OSError:
                continue
        return path in open_files


def get_file_encodings(path):
    import charset_normalizer

    MAX_BYTES_TO_ANALYZE = 1048576  # 1 MiB

    detection_result = None
    if path.startswith("http"):
        response = web.session.get(path, stream=True)
        response.raw.decode_content = True

        sample_bytes = b""
        for chunk in response.iter_content(chunk_size=16_384):  # type: ignore
            sample_bytes += chunk
            detection_result = charset_normalizer.from_bytes(sample_bytes)

            if len(sample_bytes) >= MAX_BYTES_TO_ANALYZE:
                break
            if detection_result and detection_result[0].coherence > MIN_DETECTION_COHERENCE:
                break
    else:
        with open(path, "rb") as f:
            sample_bytes = f.read(MAX_BYTES_TO_ANALYZE)

        detection_result = charset_normalizer.from_bytes(sample_bytes)

    if detection_result:
        log.info(f"The encoding of {path} is likely: {detection_result[0].encoding}")
        return [o.encoding for o in detection_result]
    return None


def head_stream(url, head_len):
    head_response = web.session.get(url, stream=True, timeout=1)
    head_response.raw.decode_content = True
    head_response.raise_for_status()

    return head_response.raw.read(head_len)


def foot_stream(url, foot_len):
    foot_response = web.session.get(url, stream=True, headers={"Range": f"bytes=-{foot_len}"}, timeout=1)
    foot_response.raw.decode_content = True

    return foot_response.raw.read(foot_len)


def head_foot_stream(url, head_len, foot_len):
    import io

    try:
        head_bytes = head_stream(url, head_len)
    except TimeoutError:
        head_bytes = b""

    try:
        foot_bytes = foot_stream(url, foot_len)
    except (TimeoutError, urllib3.exceptions.DecodeError):
        foot_bytes = b""

    stream = io.BytesIO(head_bytes + foot_bytes)
    return stream


def _detect_special_mimetype(path, ext):
    if ext in (".zarr", ".zarr/"):
        return "Zarr"
    if Path(path).is_dir():
        return "directory"
    file_type, _encoding = mimetypes.guess_type(path, strict=False)
    if file_type is not None:
        return file_type

    pandas_ext = {
        ".dta": "Stata",
        ".xlsx": "Excel",
        ".xls": "Excel",
        ".json": "JSON",
        ".jsonl": "JSON Lines",
        ".ndjson": "JSON Lines",
        ".geojson": "GeoJSON",
        ".geojsonl": "GeoJSON Lines",
        ".ndgeojson": "GeoJSON Lines",
        ".hdf": "HDF5",
        ".feather": "Feather",
        ".parquet": "Parquet",
        ".sas7bdat": "SAS",
        ".sav": "SPSS",
        ".pkl": "Pickle",
        ".orc": "ORC",
    }
    return pandas_ext.get(ext)


def _detect_magic_mimetype(path, puremagic):
    p = Path(path)
    try:
        if path.startswith("http"):
            max_head = max([len(x.byte_match) + x.offset for x in puremagic.magic_header_array])
            max_foot = max([len(x.byte_match) + abs(x.offset) for x in puremagic.magic_footer_array])
            info = puremagic.magic_stream(head_foot_stream(path, max_head, max_foot), path)
        else:
            try:
                info = puremagic.magic_file(path)
            except OSError as excinfo:
                if excinfo.errno == errno.ENXIO:
                    raise puremagic.PureError("No such device or address") from excinfo
                raise
        log.debug(info)
        return info[0].name
    except (puremagic.PureError, IndexError, ValueError):
        device_types = (
            ("socket", p.is_socket),
            ("fifo", p.is_fifo),
            ("symlink", p.is_symlink),
            ("block device", p.is_block_device),
            ("char device", p.is_char_device),
        )
        for file_type, predicate in device_types:
            if predicate():
                return file_type
        try:
            if Path(path).stat().st_size == 0:
                return "empty file"
        except Exception:
            return None
    except (FileNotFoundError, PermissionError):
        return None
    return None


@processes.with_timeout_thread(max(consts.REQUESTS_TIMEOUT) + 5)
def detect_mimetype(path):
    import puremagic

    ext = puremagic.ext_from_filename(path)
    file_type = _detect_special_mimetype(path, ext)

    if file_type is None:
        file_type = _detect_magic_mimetype(path, puremagic)

    return file_type


def retry_with_different_encodings(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except UnicodeDecodeError as exc:
            original_exc = exc

        likely_encodings = []
        detected_encoding = get_file_encodings(args[0])
        if detected_encoding:
            likely_encodings.append(detected_encoding)

        for encoding in likely_encodings + consts.COMMON_ENCODINGS:
            try:
                kwargs["encoding"] = encoding
                return func(*args, **kwargs)
            except UnicodeDecodeError:
                pass

        raise original_exc  # If no encoding worked, raise the original exception

    return wrapper


class NamedDataFrame(NamedTuple):
    df_name: str | None
    df: object


NDF = NamedDataFrame


def json_source(path: str):
    # stdin content is passed around as a literal string but pandas only treats str as a path
    # (pandas>=3 removed support for passing literal JSON strings), so wrap content in a buffer
    if not path.lstrip().startswith(("{", "[")):
        return path
    with suppress(OSError):
        if Path(path).exists():
            return path
    return StringIO(path)


def _read_sqlite_tables(path, table_name, table_index, start_row, end_row, order_by):
    import pandas as pd
    from sqlite_utils import Database

    db = Database(path)
    if table_name:
        tables = [table_name]
    else:
        tables = [
            table
            for table in db.table_names() + db.view_names()
            if not any(["_fts_" in table, table.endswith("_fts"), table.startswith("sqlite_")])
        ]
        if table_index is not None:
            tables = [tables[table_index]]

    dataframes = [
        NDF(table, pd.DataFrame(db[table].rows_where(offset=start_row, limit=end_row, order_by=order_by)))
        for table in tables
    ]
    db.close()
    return dataframes


def _read_excel_tables(path, table_name, table_index, start_row, end_row, skip_headers):
    import pandas as pd

    excel_data = pd.read_excel(
        path,
        sheet_name=table_name or table_index,
        nrows=end_row,
        skiprows=start_row,
        header=None if skip_headers else 0,
    )
    if isinstance(excel_data, pd.DataFrame):
        return [NDF(name, excel_data.loc[name]) for name in excel_data.index.levels[0]]  # type: ignore
    return list(starmap(NDF, excel_data.items()))


def _read_xarray_table(path, mimetype):
    import xarray as xr  # type: ignore

    dataset = xr.open_dataset(path) if mimetype in ("netcdf", "application/x-netcdf") else xr.open_zarr(path)
    return [NDF(None, dataset.to_dataframe())]


def _read_pandas_table(path, mimetype, start_row, end_row, encoding, skip_headers):
    import pandas as pd

    readers = {
        "hdf": lambda: pd.read_hdf(path, start=start_row, stop=end_row),
        "application/x-hdf": lambda: pd.read_hdf(path, start=start_row, stop=end_row),
        "json": lambda: pd.read_json(json_source(path), encoding=encoding),
        "application/json": lambda: pd.read_json(json_source(path), encoding=encoding),
        "jsonl": lambda: pd.read_json(json_source(path), nrows=end_row, lines=True, encoding=encoding),
        "json lines": lambda: pd.read_json(json_source(path), nrows=end_row, lines=True, encoding=encoding),
        "geojson lines": lambda: pd.read_json(json_source(path), nrows=end_row, lines=True, encoding=encoding),
        "csv": lambda: pd.read_csv(
            path, nrows=end_row, skiprows=start_row or 0, encoding=encoding, header=None if skip_headers else 0
        ),
        "text/csv": lambda: pd.read_csv(
            path, nrows=end_row, skiprows=start_row or 0, encoding=encoding, header=None if skip_headers else 0
        ),
        "lines": lambda: pd.read_csv(
            path,
            names=["text"],
            sep="\r",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "text/plain": lambda: pd.read_csv(
            path,
            names=["text"],
            sep="\r",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "plaintext": lambda: pd.read_csv(
            path,
            names=["text"],
            sep="\r",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "plain": lambda: pd.read_csv(
            path,
            names=["text"],
            sep="\r",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "wsv": lambda: pd.read_csv(
            path,
            delim_whitespace=True,
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "text/wsv": lambda: pd.read_csv(
            path,
            delim_whitespace=True,
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "text/whitespace-separated-values": lambda: pd.read_csv(
            path,
            delim_whitespace=True,
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "tsv": lambda: pd.read_csv(
            path,
            delimiter="\t",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "text/tsv": lambda: pd.read_csv(
            path,
            delimiter="\t",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "text/tab-separated-values": lambda: pd.read_csv(
            path,
            delimiter="\t",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        ),
        "parq": lambda: pd.read_parquet(path),
        "parquet": lambda: pd.read_parquet(path),
        "application/parquet": lambda: pd.read_parquet(path),
        "pkl": lambda: pd.read_pickle(path),  # Pickle is explicitly selected by the caller.
        "pickle": lambda: pd.read_pickle(path),
        "stata": lambda: pd.read_stata(path),
        "feather": lambda: pd.read_feather(path),
        "orc": lambda: pd.read_orc(path),
    }
    reader = readers.get(mimetype)
    return [NDF(None, reader())] if reader else None


def _read_html_tables(path, start_row, encoding):
    import pandas as pd

    if path.startswith("http"):
        path = StringIO(web.extract_html(path))
    return [NDF(None, dataframe) for dataframe in pd.read_html(path, skiprows=start_row, encoding=encoding)]


def _read_pdf_tables(path, start_row, end_row):
    import pandas as pd
    import camelot

    if path.startswith(("http://", "https://", "ftp://")) and " " in path:
        path = web.url_encode(path)

    dataframes = []
    for table in camelot.read_pdf(path, pages="all", suppress_stdout=False):  # type: ignore
        dataframe = table.df
        if start_row:
            dataframe = dataframe.iloc[start_row:]
        if end_row:
            dataframe = dataframe.iloc[:end_row]
        if isinstance(dataframe.columns, pd.RangeIndex):
            dataframe.columns = dataframe.iloc[0]
            dataframe = dataframe.iloc[1:]
        dataframe.columns = [" ".join(column.replace("\n", "").split()) for column in dataframe.columns]
        dataframes.append(NDF(None, dataframe))
    return dataframes


def _read_typed_tables(path, mimetype, table_name, table_index, start_row, end_row, order_by, encoding, skip_headers):
    dataframes = None
    if mimetype in ("sqlite", "sqlite3", "sqlite database file", "application/vnd.sqlite3"):
        dataframes = _read_sqlite_tables(path, table_name, table_index, start_row, end_row, order_by)
    elif mimetype in (
        "excel",
        "application/vnd.ms-excel",
        "excel spreadsheet subheader",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        dataframes = _read_excel_tables(path, table_name, table_index, start_row, end_row, skip_headers)
    elif mimetype in ("netcdf", "application/x-netcdf", "zarr"):
        dataframes = _read_xarray_table(path, mimetype)
    else:
        dataframes = _read_pandas_table(path, mimetype, start_row, end_row, encoding, skip_headers)
        if dataframes is None and mimetype in ("html", "htm", "text/html", "html document"):
            dataframes = _read_html_tables(path, start_row, encoding)
        elif dataframes is None and "pdf" in mimetype:
            dataframes = _read_pdf_tables(path, start_row, end_row)
        elif dataframes is None and "xml" in mimetype:
            import pandas as pd

            dataframes = [NDF(None, pd.read_xml(path, encoding=encoding or "utf-8"))]
        elif dataframes is None:
            message = f"{path}: Unsupported file type: {mimetype}"
            raise ValueError(message)
    return dataframes


@retry_with_different_encodings
def read_file_to_dataframes(
    path,
    table_name=None,
    table_index=None,
    start_row=None,
    end_row=None,
    order_by=None,
    encoding=None,
    mimetype=None,
    join_tables=False,
    transpose=False,
    skip_headers=False,
) -> list[NDF]:
    import pandas as pd

    if mimetype is None:
        with suppress(TimeoutError):
            mimetype = detect_mimetype(path)
    if mimetype is not None:
        mimetype = mimetype.strip().lower()
    log.info(mimetype)

    if mimetype is None:
        msg = f"{path}: File type could not be determined. Pass in --filetype"
        raise ValueError(msg)

    dfs: list[NDF] = _read_typed_tables(
        path, mimetype, table_name, table_index, start_row, end_row, order_by, encoding, skip_headers
    )

    if mimetype not in ("sqlite", "sqlite3", "sqlite database file") and table_index is not None:
        dfs = [dfs[table_index]]

    if skip_headers:
        for _df_name, df in dfs:
            df.columns = [f"column{i}" for i in range(len(df.columns))]

    if join_tables:
        dfs = [NDF(dfs[0].df_name, pd.concat([t.df for t in dfs], axis=0, ignore_index=True))]

    dfs = [NDF(t.df_name or str(table_index_as_name), t.df) for table_index_as_name, t in enumerate(dfs)]

    if transpose:

        def transpose_df(df):
            df.loc[-1] = df.columns
            df = df.sort_index().reset_index(drop=True).T
            return df

        dfs = [NDF(t.df_name, transpose_df(t.df)) for t in dfs]

    return dfs


def filter_deleted(paths):
    deleted_paths = set()

    existing_paths = []
    for p in paths:
        parent_path = os.path.dirname(p)

        if parent_path in deleted_paths:
            continue
        if not os.path.exists(parent_path):
            deleted_paths.add(parent_path)
            continue
        if not os.path.exists(p):
            continue

        existing_paths.append(p)

    return existing_paths


def get_file_stats(d):
    try:
        stat = Path(d["path"]).stat()
        d["size"] = stat.st_size

        d["time_deleted"] = 0
        d["time_created"] = int(stat.st_ctime)
        d["time_modified"] = int(stat.st_mtime)
        if stat.st_atime and stat.st_atime != stat.st_mtime:
            d["time_accessed"] = int(stat.st_atime)
    except FileNotFoundError:
        d["size"] = None
        if "time_deleted" not in d:
            d["time_deleted"] = consts.APPLICATION_START

    return d


def get_files_stats(media):
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(get_file_stats, media))
    return results


def get_file_type(d):
    try:
        d["type"] = detect_mimetype(d["path"])
    except (FileNotFoundError, TimeoutError):
        d["type"] = None
        if "time_deleted" not in d:
            d["time_deleted"] = consts.APPLICATION_START

    return d
