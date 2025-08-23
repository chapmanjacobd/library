import errno, mimetypes, os, shlex, shutil, subprocess, tempfile, time
from collections import Counter, namedtuple
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from fnmatch import fnmatch
from functools import wraps
from io import StringIO
from pathlib import Path
from shutil import which

import urllib3

from library.utils import consts, path_utils, printing, processes, strings, web
from library.utils.log_utils import log


def scan_stats(files: int, filtered_files: int, folders: int, filtered_folders: int):
    return (
        f"""Files: {files}{f' [{filtered_files} ignored]' if filtered_files else ''}"""
        f""" Folders: {folders}{f' [{filtered_folders} ignored]' if filtered_folders else ''}"""
    )


def rglob(
    base_dir: str | Path,
    extensions: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    include: Iterable[str] | None = None,
    quiet=False,
) -> tuple[set[str], set[str], set[str]]:
    if extensions is not None:
        extensions = tuple(f".{ext.lstrip('.')}" for ext in extensions)

    files = set()
    filtered_files = set()
    filtered_folders = set()
    folders = set()
    stack = [base_dir]
    while stack:
        current_dir = stack.pop()
        try:
            scanned_dir = os.scandir(current_dir)
        except (FileNotFoundError, PermissionError):
            pass
        except OSError as e:
            if e.errno == 23:  # Too many open files
                raise e
            elif e.errno == 5:  # Input/output error
                log.exception("Input/output error: check dmesg. Skipping folder %s", current_dir)
            raise
        else:
            for entry in scanned_dir:
                if entry.is_dir(follow_symlinks=False):
                    if exclude and any(entry.name == pattern or fnmatch(entry.path, pattern) for pattern in exclude):
                        filtered_folders.add(entry.path)
                        continue
                    if include and not any(
                        entry.name == pattern or fnmatch(entry.path, pattern) for pattern in include
                    ):
                        filtered_folders.add(entry.path)
                        continue
                    folders.add(entry.path)
                    stack.append(entry.path)
                elif entry.is_symlink():
                    continue
                else:  # file or close enough
                    if extensions and not entry.path.lower().endswith(extensions):
                        filtered_files.add(entry.path)
                        continue
                    if include and not any(
                        entry.name == pattern or fnmatch(entry.path, pattern) for pattern in include
                    ):
                        filtered_files.add(entry.path)
                        continue
                    if exclude and any(entry.name == pattern or fnmatch(entry.path, pattern) for pattern in exclude):
                        filtered_files.add(entry.path)
                        continue
                    files.add(entry.path)

            if not quiet:
                printing.print_overwrite(
                    f"[{base_dir}] {scan_stats(len(files), len(filtered_files), len(folders), len(filtered_folders))}"
                )

    if not consts.PYTEST_RUNNING and not quiet:
        print(f"\r[{base_dir}] {scan_stats(len(files), len(filtered_files), len(folders), len(filtered_folders))}")

    filtered_extensions = Counter(Path(s).suffix for s in filtered_files)
    log.info("Filtered extensions: %s", filtered_extensions)

    return files, filtered_files, folders


def rglob_gen(
    base_dir: str | Path,
    extensions: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    include: Iterable[str] | None = None,
):
    if extensions is not None:
        extensions = tuple(f".{ext.lstrip('.')}" for ext in extensions)

    folders = set()
    stack = [base_dir]
    while stack:
        current_dir = stack.pop()
        try:
            scanned_dir = os.scandir(current_dir)
        except (FileNotFoundError, PermissionError):
            pass
        except OSError as e:
            if e.errno == 23:  # Too many open files
                raise e
            elif e.errno == 5:  # Input/output error
                log.exception("Input/output error: check dmesg. Skipping folder %s", current_dir)
            raise
        else:
            for entry in scanned_dir:
                if entry.is_dir(follow_symlinks=False):
                    if exclude and any(entry.name == pattern or fnmatch(entry.path, pattern) for pattern in exclude):
                        continue
                    if include and not any(
                        entry.name == pattern or fnmatch(entry.path, pattern) for pattern in include
                    ):
                        continue
                    folders.add(entry.path)
                    stack.append(entry.path)
                elif entry.is_symlink():
                    continue
                else:  # file or close enough
                    if extensions and not entry.path.lower().endswith(extensions):
                        continue
                    if include and not any(
                        entry.name == pattern or fnmatch(entry.path, pattern) for pattern in include
                    ):
                        continue
                    if exclude and any(entry.name == pattern or fnmatch(entry.path, pattern) for pattern in exclude):
                        continue
                    yield entry.path


def fd_rglob_gen(
    base_dir: str | Path,
    extensions: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    include: Iterable[str] | None = None,
):
    fd_command = ["fd", "-HI", "-tf", "--absolute-path", "-0"]

    if extensions:
        ext_args = []
        for ext in extensions:
            ext_args.extend(["-e", ext.lstrip(".")])
        fd_command.extend(ext_args)

    if exclude:
        for pattern in exclude:
            fd_command.extend(["-E", pattern])

    fd_command.extend([".", str(base_dir)])
    process = subprocess.Popen(fd_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        if process.stdout is None:
            break
        chunk = process.stdout.read(4096)
        if not chunk:  # End of stream
            break

        for path_bytes in chunk.split(b"\0"):
            if path_bytes:  # empty bytes at the end
                path = path_bytes.decode("utf-8")

                if include:
                    if not any(fnmatch(path, pattern) for pattern in include):
                        continue

                yield path

    exit_code = process.wait()
    if process.stderr:
        stderr = process.stderr.read().decode("utf-8")
        if stderr:
            log.error(f"fd stderr: {stderr}")

    if exit_code != 0:
        raise subprocess.CalledProcessError(exit_code, fd_command)


def file_temp_copy(src) -> str:
    fo_dest = tempfile.NamedTemporaryFile(delete=False)
    with open(src, "r+b") as fo_src:
        shutil.copyfileobj(fo_src, fo_dest.file)
    fo_dest.seek(0)
    fname = fo_dest.name
    fo_dest.close()
    return fname


def trash(args, path: Path | str, detach=True) -> None:
    if path and Path(path).exists():
        if str(path).startswith("/net/"):
            Path(path).unlink(missing_ok=True)
            return

        trash_put = which(args.override_trash)
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
            except OSError:
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


def copy_file(source_file, destination_file, simulate=False):
    if simulate:
        print("cp", source_file, destination_file)
    else:
        try:
            shutil.copy2(source_file, destination_file)
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.EXDEV):
                os.makedirs(os.path.dirname(destination_file), exist_ok=True)
                shutil.copy2(source_file, destination_file)  # try again
            else:
                raise


def copy(args, src, dest):
    dest = path_utils.gen_rel_path(src, dest, ":")
    if getattr(args, "clean_path", True):
        dest = path_utils.clean_path(os.fsencode(dest))
    else:
        dest = str(dest)

    if src == dest:
        return src

    copy_file(src, dest, simulate=args.simulate)
    return dest


def rename_no_replace(src, dst):
    if os.path.exists(dst) and not os.path.isdir(dst):
        msg = f"The destination file {dst} already exists."
        raise FileExistsError(msg)
    os.rename(src, dst)


def rename_move_file(source_file, destination_file, simulate=False):
    if simulate:
        print("mv", source_file, destination_file)
    else:
        try:
            os.rename(source_file, destination_file)  # performance
        except OSError as e:
            if e.errno == errno.ENOENT:
                try:
                    os.makedirs(os.path.dirname(destination_file), exist_ok=True)
                    os.rename(source_file, destination_file)  # try again
                except OSError as e:
                    if e.errno == errno.EXDEV:  # Cross-device
                        shutil.move(source_file, destination_file)  # Fallback to shutil.move
                    else:
                        raise
            elif e.errno == errno.EXDEV:  # Cross-device
                shutil.move(source_file, destination_file)  # Fallback to shutil.move
            else:
                raise


def rel_move(args, src, dest):
    dest = path_utils.gen_rel_path(src, dest, ":")
    if getattr(args, "clean_path", True):
        dest = path_utils.clean_path(os.fsencode(dest))
    else:
        dest = str(dest)

    if src == dest:
        return src

    rename_move_file(src, dest, simulate=args.simulate)
    return dest


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
            elif detection_result and detection_result[0].coherence > 0.8:
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
                info = puremagic.magic_file(path)
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

        except FileNotFoundError:
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
        for df_name, df in dfs:
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
        with suppress(TimeoutError):
            d["type"] = detect_mimetype(d["path"])
    except FileNotFoundError:
        d["type"] = None
        if "time_deleted" not in d:
            d["time_deleted"] = consts.APPLICATION_START

    return d


def alt_name(file_path):
    file_path = Path(file_path)
    alternative_path = file_path
    counter = 1
    while alternative_path.exists():
        new_name = f"{file_path.stem}_{counter}{file_path.suffix}"
        alternative_path = file_path.with_name(new_name)
        counter += 1
    return str(alternative_path)


def gen_paths(args, default_exts=None):
    if args.paths is None:
        processes.exit_error("No paths passed in")

    if args.from_json:
        for path in args.paths:
            json_data = strings.safe_json_loads(path)
            if isinstance(json_data, list):
                for json_item in json_data:
                    yield json_item["path"]
            elif isinstance(json_data, dict):
                yield json_data["path"]
            else:
                raise TypeError
    else:
        for path in args.paths:
            if path.strip():
                try:
                    is_dir = os.path.isdir(path)
                except OSError:
                    yield path
                else:
                    if is_dir:
                        yield from rglob(path, args.ext or default_exts, getattr(args, "exclude", None))[0]
                    else:
                        yield path


def gen_d(args, default_exts=None):
    if args.paths is None:
        processes.exit_error("No data passed in")

    if args.from_json:
        for path in args.paths:
            json_data = strings.safe_json_loads(path)
            if isinstance(json_data, list):
                for json_item in json_data:
                    yield json_item
            elif isinstance(json_data, dict):
                yield json_data
            else:
                raise TypeError
    else:
        for path in args.paths:
            if path.strip():
                try:
                    is_dir = os.path.isdir(path)
                except OSError:
                    yield {"path": path}
                else:
                    if is_dir:
                        for sp in rglob(str(path), args.ext or default_exts, getattr(args, "exclude", None))[0]:
                            yield {"path": sp}
                    else:
                        yield {"path": path}
