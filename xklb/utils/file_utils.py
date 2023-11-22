import os, shlex, shutil, tempfile, time
from functools import wraps
from pathlib import Path
from shutil import which
from typing import Union

from xklb.utils import consts, file_utils, processes, web
from xklb.utils.log_utils import log


def file_temp_copy(src) -> str:
    fo_dest = tempfile.NamedTemporaryFile(delete=False)
    with open(src, "r+b") as fo_src:
        shutil.copyfileobj(fo_src, fo_dest)
    fo_dest.seek(0)
    fname = fo_dest.name
    fo_dest.close()
    return fname


def trash(path: Union[Path, str], detach=True) -> None:
    if Path(path).exists():
        trash_put = which("trash-put") or which("trash")
        if trash_put is not None:
            if not detach:
                processes.cmd(trash_put, path, strict=False)
                return
            try:
                processes.cmd_detach(trash_put, path)
            except Exception:
                processes.cmd(trash_put, path, strict=False)
        else:
            Path(path).unlink(missing_ok=True)


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
            except (OSError, IOError):
                continue
        return path in open_files


def filter_file(path, sieve) -> None:
    with open(path) as fr:
        lines = fr.readlines()
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp:
            temp.writelines(line for line in lines if line.rstrip() not in sieve)
            temp.flush()
            os.fsync(temp.fileno())
    shutil.copy(temp.name, path)
    Path(temp.name).unlink()


def tempdir_unlink(pattern):
    temp_dir = tempfile.gettempdir()
    cutoff = time.time() - 15 * 60  # 15 minutes in seconds
    for p in Path(temp_dir).glob(pattern):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
        except FileNotFoundError:  # glob->stat() racing
            pass


def resolve_absolute_path(s):
    p = Path(s).expanduser()
    if p.is_absolute():
        p = p.resolve()
        if p.exists():
            return str(p)
    return s  # relative path


def resolve_absolute_paths(paths):
    if paths is None:
        return paths
    return [resolve_absolute_path(s) for s in paths]


def fast_glob(path_dir, limit=100):
    files = []
    with os.scandir(path_dir) as entries:
        for entry in entries:
            if entry.is_file():
                files.append(entry.path)
                if len(files) == limit:
                    break
    return sorted(files)


def move_files(file_list):
    for existing_path, new_path in file_list:
        try:
            os.rename(existing_path, new_path)
        except Exception:
            try:
                parent_dir = os.path.dirname(new_path)
                os.makedirs(parent_dir, exist_ok=True)

                shutil.move(existing_path, new_path)
            except Exception:
                log.exception("Could not move %s", existing_path)


def move_files_bash(file_list):
    move_sh = """#!/bin/sh
existing_path=$1
new_path=$2

# Attempt to rename the file/directory
mv -Tn "$existing_path" "$new_path" 2>/dev/null

if [ $? -ne 0 ]; then
    mkdir -p $(dirname "$new_path")
    mv -Tn "$existing_path" "$new_path"
fi
"""
    move_sh_path = Path(tempfile.mktemp(dir=consts.TEMP_SCRIPT_DIR, prefix="move_", suffix=".sh"))
    move_sh_path.write_text(move_sh)
    move_sh_path.chmod(move_sh_path.stat().st_mode | 0o100)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv") as temp:
        temp.writelines(
            f"{shlex.quote(existing_path)}\t{shlex.quote(new_path)}\n" for existing_path, new_path in file_list
        )
        temp.flush()
        os.fsync(temp.fileno())

        print(f"""### Move {len(file_list)} files to new folders: ###""")
        print(rf"PARALLEL_SHELL=sh parallel --colsep '\t' -a {temp.name} -j 20 {move_sh_path}")


def get_file_encoding(path):
    import chardet

    if path.startswith("http"):
        response = web.requests_session().get(path, stream=True)
        detector = chardet.UniversalDetector()
        num_bytes = 0
        for chunk in response.iter_content(chunk_size=16_384):
            if num_bytes > 1048576:  # 1MiB
                break
            detector.feed(chunk)
            if detector.done:
                break
            num_bytes += len(chunk)
        detector.close()

        encoding = detector.result["encoding"]
    else:
        with open(path, "rb") as f:
            sample = f.read(1048576)  # 1 MiB

        encoding = chardet.detect(sample)["encoding"]

    if encoding:
        log.info(f"The encoding of {path} is likely: {encoding}")
    return encoding


def head_foot_stream(url, head_len, foot_len):
    import io

    head_response = web.requests_session().get(url, stream=True)
    head_response.raise_for_status()
    head_bytes = head_response.raw.read(head_len)

    foot_response = web.requests_session().get(url, stream=True, headers={"Range": f"bytes={-foot_len}"})
    foot_bytes = foot_response.raw.read(foot_len)

    stream = io.BytesIO(head_bytes + foot_bytes)
    return stream


def mimetype(path):
    import mimetypes

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
                info = puremagic.magic_file(path)
            log.debug(info)
            file_type = info[0].name
        except (puremagic.PureError, IndexError):
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
        except FileNotFoundError:
            return

    return file_type


def retry_with_different_encodings(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except UnicodeDecodeError as exc:
            original_exc = exc

        likely_encodings = []
        detected_encoding = get_file_encoding(args[0])
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


@retry_with_different_encodings
def read_file_to_dataframes(
    path, table_name=None, table_index=None, start_row=None, end_row=None, order_by=None, encoding=None, mimetype=None
):
    import pandas as pd

    if mimetype is None:
        mimetype = file_utils.mimetype(path)
    if mimetype is not None:
        mimetype = mimetype.strip().lower()
    log.info(mimetype)

    if mimetype in ("sqlite", "sqlite3", "sqlite database file"):
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
            if table_index:
                tables = [table_index]

        dfs = []
        for table in tables:
            df = pd.DataFrame(db[table].rows_where(offset=start_row, limit=end_row, order_by=order_by))
            df.name = table
            dfs.append(df)
        db.close()
    elif mimetype in (
        "excel",
        "application/vnd.ms-excel",
        "excel spreadsheet subheader",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        excel_data = pd.read_excel(path, sheet_name=table_name or table_index, nrows=end_row, skiprows=start_row)
        dfs = []
        if isinstance(excel_data, pd.DataFrame):
            worksheet_names = excel_data.index.levels[0]  # type: ignore
            for name in worksheet_names:
                df = excel_data.loc[name]
                df.name = name
                dfs.append(df)
        else:
            for worksheet_name, df in excel_data.items():
                df.name = worksheet_name
                dfs.append(df)
    elif mimetype in (
        "netcdf",
        "application/x-netcdf",
    ):
        import xarray as xr

        ds = xr.open_dataset(path)
        dfs = [ds.to_dataframe()]
    elif mimetype in ("zarr",):
        import xarray as xr

        ds = xr.open_zarr(path)
        dfs = [ds.to_dataframe()]
    elif mimetype in (
        "hdf",
        "application/x-hdf",
    ):
        dfs = [pd.read_hdf(path, start=start_row, stop=end_row)]
    elif mimetype in (
        "json",
        "application/json",
    ):
        dfs = [pd.read_json(path, encoding=encoding)]
    elif mimetype in ("jsonl", "json lines", "geojson lines"):
        dfs = [pd.read_json(path, nrows=end_row, lines=True, encoding=encoding)]
    elif mimetype in (
        "csv",
        "text/csv",
    ):
        dfs = [pd.read_csv(path, nrows=end_row, skiprows=start_row or 0, encoding=encoding)]
    elif mimetype in (
        "tsv",
        "text/tsv",
        "text/tab-separated-values",
    ):
        dfs = [pd.read_csv(path, delimiter="\t", nrows=end_row, skiprows=start_row or 0, encoding=encoding)]
    elif mimetype in ("parq", "parquet", "application/parquet"):
        dfs = [pd.read_parquet(path)]
    elif mimetype in ("pkl", "pickle", "application/octet-stream"):
        dfs = [pd.read_pickle(path)]
    elif mimetype in (
        "html",
        "htm",
        "text/html",
    ):
        dfs = pd.read_html(path, skiprows=start_row, encoding=encoding)
    elif mimetype in ("stata",):
        dfs = [pd.read_stata(path)]
    elif mimetype in ("feather",):
        dfs = [pd.read_feather(path)]
    elif mimetype in ("orc",):
        dfs = [pd.read_orc(path)]
    elif mimetype in (
        "xml",
        "text/xml",
    ):
        dfs = [pd.read_xml(path, encoding=encoding)]
    else:
        msg = f"{path}: Unsupported file type: {mimetype}"
        raise ValueError(msg)

    for table_index, df in enumerate(dfs):
        if not hasattr(df, "name"):
            df.name = str(table_index)

    return dfs
