import errno, os, shlex, shutil, subprocess, tempfile, time
from collections import Counter
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from shutil import which

from library.utils import consts, path_utils, printing, processes, strings
from library.utils.log_utils import log


def rename_move_file(source_file, destination_file, simulate=False):
    if simulate:
        print("mv", source_file, destination_file)
    else:
        try:
            os.rename(source_file, destination_file)  # performance
        except PermissionError:
            log.warning("PermissionError. Could not rename %s into %s", source_file, os.path.dirname(destination_file))
        except OSError as excinfo:
            if excinfo.errno == errno.ENOENT:
                try:
                    os.makedirs(os.path.dirname(destination_file), exist_ok=True)
                    os.rename(source_file, destination_file)  # try again
                except FileNotFoundError:
                    log.error("FileNotFoundError. %s", source_file)
                except OSError as excinfo:
                    if excinfo.errno == errno.EXDEV:  # Cross-device
                        shutil.move(source_file, destination_file)  # Fallback to shutil.move
                    else:
                        raise
            elif excinfo.errno == errno.EXDEV:  # Cross-device
                shutil.move(source_file, destination_file)  # Fallback to shutil.move
            else:
                raise


def rename_no_replace(src, dst):
    if os.path.exists(dst) and not os.path.isdir(dst):
        msg = f"The destination file {dst} already exists."
        raise FileExistsError(msg)
    os.rename(src, dst)


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
    base_dir_print = str(base_dir).encode("utf-8", errors="replace").decode("utf-8")
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
        except OSError as excinfo:
            if excinfo.errno == errno.ENFILE:  # Too many open files
                raise
            elif excinfo.errno == errno.EIO:  # Input/output error
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
                    f"[{base_dir_print}] {scan_stats(len(files), len(filtered_files), len(folders), len(filtered_folders))}"
                )

    if not consts.PYTEST_RUNNING and not quiet:
        print(
            f"\r[{base_dir_print}] {scan_stats(len(files), len(filtered_files), len(folders), len(filtered_folders))}"
        )

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
        except OSError as excinfo:
            if excinfo.errno == errno.ENFILE:  # errno.errorcode[23] Too many open files
                raise
            elif excinfo.errno == errno.EIO:
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


def fast_glob(path_dir, limit=100):
    files = []
    with os.scandir(path_dir) as entries:
        for entry in entries:
            if entry.is_file():
                files.append(entry.path)
                if len(files) == limit:
                    break
    return sorted(files)


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
                yield from json_data
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

                if include and not any(fnmatch(path, pattern) for pattern in include):
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


def tempdir_unlink(pattern):
    temp_dir = tempfile.gettempdir()
    cutoff = time.time() - 15 * 60  # 15 minutes in seconds
    for p in Path(temp_dir).glob(pattern):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
        except FileNotFoundError:  # glob->stat() racing
            pass


def copy_file(source_file, destination_file, simulate=False):
    if simulate:
        print("cp", source_file, destination_file)
    else:
        try:
            shutil.copy2(source_file, destination_file)
        except OSError as excinfo:
            if excinfo.errno in (errno.ENOENT, errno.EXDEV):
                os.makedirs(os.path.dirname(destination_file), exist_ok=True)
                shutil.copy2(source_file, destination_file)  # try again
            else:
                raise


def copy(args, src: str, dest: str):
    dest = path_utils.gen_rel_path(src, dest, ":")
    if getattr(args, "clean_path", True):
        dest = path_utils.clean_path(os.fsencode(dest))
    else:
        dest = str(dest)

    if src == dest:
        return src

    copy_file(src, dest, simulate=args.simulate)
    return dest


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


def filter_file(path, sieve) -> None:
    with open(path) as fr:
        lines = fr.readlines()
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp:
            temp.writelines(line for line in lines if line.rstrip() not in sieve)
            temp.flush()
            os.fsync(temp.fileno())
    shutil.copy(temp.name, path)
    Path(temp.name).unlink()


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


def rel_move(args, src: str, dest: str):
    dest = path_utils.gen_rel_path(src, dest, ":")
    if getattr(args, "clean_path", True):
        dest = path_utils.clean_path(os.fsencode(dest), dedupe_parts=True)
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


def flatten_wrapper_folder(output_path):
    entries = [e for e in os.listdir(output_path) if not e.startswith(".")]
    if len(entries) == 1:
        entry_path = os.path.join(output_path, entries[0])
        if os.path.isdir(entry_path):
            log.warning("Flattening wrapper folder: %s", entries[0])

            items = os.listdir(entry_path)

            conflict_item = None
            # Move items that don't conflict
            for item in items:
                if os.path.join(output_path, item) == entry_path:
                    conflict_item = item
                    continue
                src = os.path.join(entry_path, item)
                dst = os.path.join(output_path, item)
                rename_move_file(src, dst)

            # Handle conflict item if it exists
            if conflict_item:
                src = os.path.join(entry_path, conflict_item)
                temp_dst = os.path.join(output_path, conflict_item + ".tmp")
                rename_move_file(src, temp_dst)
                os.rmdir(entry_path)
                rename_move_file(temp_dst, os.path.join(output_path, conflict_item))
            else:
                os.rmdir(entry_path)
