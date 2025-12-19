import errno, mimetypes, os
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import wraps
from io import StringIO
from pathlib import Path

import urllib3

from library.utils import consts, processes, web
from library.utils.log_utils import log


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
            if detection_result and detection_result[0].coherence > 0.8:
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


@processes.with_timeout_thread(max(consts.REQUESTS_TIMEOUT) + 5)
def detect_mimetype(path):
    import puremagic

    p = Path(path)

    file_type = None
    ext = puremagic.ext_from_filename(path)
    if ext in (".zarr", ".zarr/"):
        file_type = "Zarr"
    elif p.is_dir():
        file_type = "directory"
    else:
        file_type, encoding = mimetypes.guess_type(path, strict=False)

    if ext and file_type is None:
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
        file_type = pandas_ext.get(ext)

    if file_type is None:
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
                        raise puremagic.PureError("No such device or address")
                    else:
                        raise
            log.debug(info)
            file_type = info[0].name
        except (puremagic.PureError, IndexError, ValueError):
            if p.is_socket():
                file_type = "socket"
            elif p.is_fifo():
                file_type = "fifo"
            elif p.is_symlink():
                file_type = "symlink"
            elif p.is_block_device():
                file_type = "block device"
            elif p.is_char_device():
                file_type = "char device"
            try:
                if Path(path).stat().st_size == 0:
                    file_type = "empty file"
            except Exception:
                return None

        except (FileNotFoundError, PermissionError):
            return None

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


NDF = namedtuple("NamedDataFrame", ["df_name", "df"])


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

    dfs: list[NDF] = []

    if mimetype in ("sqlite", "sqlite3", "sqlite database file", "application/vnd.sqlite3"):
        import pandas as pd
        from sqlite_utils import Database

        db = Database(path)

        if table_name:
            tables = [table_name]
        else:
            tables = [
                s
                for s in db.table_names() + db.view_names()
                if not any(["_fts_" in s, s.endswith("_fts"), s.startswith("sqlite_")])
            ]
            if table_index is not None:
                tables = [tables[table_index]]

        for table in tables:
            df = pd.DataFrame(db[table].rows_where(offset=start_row, limit=end_row, order_by=order_by))
            dfs.append(NDF(table, df))
        db.close()
    elif mimetype in (
        "excel",
        "application/vnd.ms-excel",
        "excel spreadsheet subheader",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        excel_data = pd.read_excel(
            path,
            sheet_name=table_name or table_index,
            nrows=end_row,
            skiprows=start_row,
            header=None if skip_headers else 0,
        )

        if isinstance(excel_data, pd.DataFrame):
            worksheet_names = excel_data.index.levels[0]  # type: ignore
            for name in worksheet_names:
                df = excel_data.loc[name]
                dfs.append(NDF(name, df))
        else:
            for worksheet_name, df in excel_data.items():
                dfs.append(NDF(worksheet_name, df))
    elif mimetype in (
        "netcdf",
        "application/x-netcdf",
    ):
        import xarray as xr  # type: ignore

        ds = xr.open_dataset(path)
        df = ds.to_dataframe()
        dfs.append(NDF(None, df))
    elif mimetype in ("zarr",):
        import xarray as xr  # type: ignore

        ds = xr.open_zarr(path)
        df = ds.to_dataframe()
        dfs.append(NDF(None, df))
    elif mimetype in (
        "hdf",
        "application/x-hdf",
    ):
        df = pd.read_hdf(path, start=start_row, stop=end_row)
        dfs.append(NDF(None, df))
    elif mimetype in (
        "json",
        "application/json",
    ):
        df = pd.read_json(path, encoding=encoding)
        dfs.append(NDF(None, df))
    elif mimetype in ("jsonl", "json lines", "geojson lines"):
        df = pd.read_json(StringIO(path), nrows=end_row, lines=True, encoding=encoding)
        dfs.append(NDF(None, df))
    elif mimetype in (
        "csv",
        "text/csv",
    ):
        df = pd.read_csv(
            path, nrows=end_row, skiprows=start_row or 0, encoding=encoding, header=None if skip_headers else 0
        )
        dfs.append(NDF(None, df))
    elif mimetype in (
        "lines",
        "text/plain",
        "plaintext",
        "plain",
    ):
        df = pd.read_csv(
            path,
            names=["text"],
            sep="\r",  # just something to keep the parser busy
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        )
        dfs.append(NDF(None, df))
    elif mimetype in (
        "wsv",
        "text/wsv",
        "text/whitespace-separated-values",
    ):
        df = pd.read_csv(
            path,
            delim_whitespace=True,
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        )
        dfs.append(NDF(None, df))
    elif mimetype in (
        "tsv",
        "text/tsv",
        "text/tab-separated-values",
    ):
        df = pd.read_csv(
            path,
            delimiter="\t",
            nrows=end_row,
            skiprows=start_row or 0,
            encoding=encoding,
            header=None if skip_headers else 0,
        )
        dfs.append(NDF(None, df))
    elif mimetype in ("parq", "parquet", "application/parquet"):
        df = pd.read_parquet(path)
        dfs.append(NDF(None, df))
    elif mimetype in ("pkl", "pickle", "application/octet-stream"):
        df = pd.read_pickle(path)
        dfs.append(NDF(None, df))
    elif mimetype in (
        "html",
        "htm",
        "text/html",
        "html document",
    ):
        if path.startswith("http"):
            path = StringIO(web.extract_html(path))
        dfs.extend(NDF(None, df) for df in pd.read_html(path, skiprows=start_row, encoding=encoding))
    elif mimetype in ("stata",):
        df = pd.read_stata(path)
        dfs.append(NDF(None, df))
    elif mimetype in ("feather",):
        df = pd.read_feather(path)
        dfs.append(NDF(None, df))
    elif mimetype in ("orc",):
        df = pd.read_orc(path)
        dfs.append(NDF(None, df))
    elif "pdf" in mimetype:
        import camelot

        if path.startswith(("http://", "https://", "ftp://")) and " " in path:
            path = web.url_encode(path)  # camelot does not like spaces in URLs...

        for t in camelot.read_pdf(path, pages="all", suppress_stdout=False):  # type: ignore
            df = t.df
            if start_row:
                df = df.iloc[start_row:]
            if end_row:
                df = df.iloc[:end_row]
            if isinstance(df.columns, pd.RangeIndex):
                new_column_names = df.iloc[0]
                df = df.iloc[1:]
                df.columns = new_column_names
            df.columns = [" ".join(col.replace("\n", "").split()) for col in df.columns]
            dfs.append(NDF(None, df))
    elif "xml" in mimetype:
        df = pd.read_xml(path, encoding=encoding or "utf-8")
        dfs.append(NDF(None, df))
    else:
        msg = f"{path}: Unsupported file type: {mimetype}"
        raise ValueError(msg)

    if mimetype not in ("sqlite", "sqlite3", "sqlite database file") and table_index is not None:
        dfs = [dfs[table_index]]

    if skip_headers:
        for _df_name, df in dfs:
            df.columns = [f"column{i}" for i in range(len(df.columns))]

    if join_tables:
        dfs = [NDF(dfs[0].df_name, pd.concat([t.df for t in dfs], axis=0, ignore_index=True))]

    dfs = [NDF(t.df_name if t.df_name else str(table_index_as_name), t.df) for table_index_as_name, t in enumerate(dfs)]

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
