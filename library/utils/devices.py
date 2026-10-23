import os, random, shlex, shutil, subprocess, sys, time, webbrowser
from pathlib import Path

from library.file import sample_compare
from library.utils import arggroups, consts, file_utils, path_utils, processes, strings
from library.utils.log_utils import log

webbrowser.register("termux-open-url '%s'", None)


def catt_default_device() -> str:
    """Catt's own configured speaker, i.e. options.device in ~/.config/catt/catt.cfg."""
    config = Path.home() / ".config" / "catt" / "catt.cfg"
    if not config.exists():
        return ""
    for line in config.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "device":
            return value.strip()
    return ""


def get_ip_of_chromecast(device_name) -> str:
    from pychromecast import discovery

    cast_infos, browser = discovery.discover_listed_chromecasts(friendly_names=[device_name])
    browser.stop_discovery()
    if not cast_infos:
        log.error("Target chromecast device not found")
        raise SystemExit(53)

    return cast_infos[0].host


def clear_input() -> None:
    if consts.IS_LINUX:
        from termios import TCIFLUSH, tcflush

        tcflush(sys.stdin, TCIFLUSH)
    elif consts.IS_MAC:
        import select

        while select.select([sys.stdin], [], [], 0.01) == ([sys.stdin], [], []):
            sys.stdin.read(1)
    elif consts.IS_WINDOWS:
        if getattr(clear_input, "kbhit", None) is None:
            from msvcrt import getch, kbhit  # type: ignore

            clear_input.kbhit = kbhit
            clear_input.getch = getch

        # Try to flush the buffer
        while clear_input.kbhit():
            clear_input.getch()


class InteractivePromptError(Exception):
    pass


InteractivePrompt = InteractivePromptError


def confirm(*args, **kwargs) -> bool:
    from rich.prompt import Confirm

    if consts.PYTEST_RUNNING:
        raise InteractivePrompt

    sys.stdout.flush()
    clear_input()
    return Confirm.ask(*args, **kwargs, default=False)


def preserve_root(p):
    assert p != os.sep
    drive, realpath = os.path.splitdrive(p)
    assert realpath
    assert os.path.normpath(p) != os.path.normpath(drive)


def rename(args, src, dst):
    if args.simulate:
        print("rename", src, dst)
    else:
        log.debug("rename\t%s\t%s", src, dst)
        os.rename(src, dst)


def unlink(args, p):
    if args.simulate:
        print("unlink", p)
    else:
        log.debug("unlink\t%s", p)
        os.unlink(p)


def rmtree(args, p):
    if args.simulate:
        print("rmtree", p)
    elif os.path.isdir(p):
        log.debug("rmtree\t%s", p)
        shutil.rmtree(p)
    else:
        log.debug("unlink\t%s", p)
        os.unlink(p)


def log_size_diff(src_size, dst_size):
    src_size_str = strings.file_size(src_size)
    dst_size_str = strings.file_size(dst_size)
    diff_size_str = strings.file_size(abs(src_size - dst_size))
    if src_size == dst_size:
        print(f"Source and destination are the same size: {src_size_str}")
    elif src_size > dst_size:
        print(f"Source ({src_size_str}) is {dst_size_str} larger than destination ({diff_size_str})")
    elif src_size < dst_size:
        print(f"Source ({src_size_str}) is {dst_size_str} smaller than destination ({diff_size_str})")


def alt_name(file_path):
    file_path = Path(file_path)
    alternative_path = file_path
    counter = 1
    while alternative_path.exists():
        new_name = f"{file_path.stem}_{counter}{file_path.suffix}"
        alternative_path = file_path.with_name(new_name)
        counter += 1
    return str(alternative_path)


def _apply_file_over_file_optional(args, source, destination, src_size, dst_size, option):
    predicates = {
        arggroups.FileOverFileOptional.DELETE_DEST_HASH: lambda: sample_compare.sample_cmp(
            source, destination, ignore_holes=True
        ),
        arggroups.FileOverFileOptional.DELETE_DEST_SIZE: lambda: src_size == dst_size,
        arggroups.FileOverFileOptional.DELETE_DEST_LARGER: lambda: src_size < dst_size,
        arggroups.FileOverFileOptional.DELETE_DEST_SMALLER: lambda: src_size > dst_size,
        arggroups.FileOverFileOptional.DELETE_SRC_HASH: lambda: sample_compare.sample_cmp(
            source, destination, ignore_holes=True
        ),
        arggroups.FileOverFileOptional.DELETE_SRC_SIZE: lambda: src_size == dst_size,
        arggroups.FileOverFileOptional.DELETE_SRC_LARGER: lambda: src_size > dst_size,
        arggroups.FileOverFileOptional.DELETE_SRC_SMALLER: lambda: src_size < dst_size,
        arggroups.FileOverFileOptional.SKIP_HASH: lambda: sample_compare.sample_cmp(
            source, destination, ignore_holes=True
        ),
        arggroups.FileOverFileOptional.SKIP_SIZE: lambda: src_size == dst_size,
        arggroups.FileOverFileOptional.SKIP_LARGER: lambda: src_size > dst_size,
        arggroups.FileOverFileOptional.SKIP_SMALLER: lambda: src_size < dst_size,
    }
    if not predicates[option]():
        return source, False

    if option.startswith("delete-dest"):
        unlink(args, destination)
    elif option.startswith("delete-src"):
        unlink(args, source)
        source = None
    else:
        source = None
    return source, True


def _apply_file_over_file_required(args, source, destination, src_size, dst_size, option):
    actions = {
        arggroups.FileOverFile.SKIP: lambda: (None, destination),
        arggroups.FileOverFile.DELETE_DEST: lambda: (source, _unlink_destination(args, destination)),
        arggroups.FileOverFile.RENAME_SRC: lambda: (source, alt_name(destination)),
        arggroups.FileOverFile.RENAME_DEST: lambda: (source, _rename_destination(args, destination)),
        arggroups.FileOverFile.DELETE_SRC: lambda: (_delete_source(args, source), destination),
    }
    if option == arggroups.FileOverFile.DELETE_DEST_ASK:
        print(source)
        print("  -->", destination)
        log_size_diff(src_size, dst_size)
        if confirm("Replace destination file?"):
            unlink(args, destination)
        return source, destination
    return actions[option]()


def _unlink_destination(args, destination):
    unlink(args, destination)
    return destination


def _rename_destination(args, destination):
    rename(args, destination, alt_name(destination))
    return destination


def _delete_source(args, source):
    unlink(args, source)


def _clobber_existing_file(args, source, destination):
    if not os.path.exists(source):
        log.error("Source file does not exist: %s", source)
        return None, destination

    src_stat = os.stat(source)
    dst_stat = os.stat(destination)
    if os.path.samestat(src_stat, dst_stat):
        log.info("Destination is the same as source\t%s", destination)
        return None, destination

    src_size = src_stat.st_blocks if consts.NOT_WINDOWS and src_stat.st_blocks else src_stat.st_size
    dst_size = dst_stat.st_blocks if consts.NOT_WINDOWS and dst_stat.st_blocks else dst_stat.st_size
    if dst_size == 0 or dst_stat.st_size == 0:
        log.debug("Overwriting empty file destination %s\t%s", source, destination)
        unlink(args, destination)
        return source, destination

    log.info("File Over File conflict\t%s\t%s", source, destination)
    optional_options = set(vars(arggroups.FileOverFileOptional).values())
    for option in args.file_over_file:
        log.debug(option)
        if option in optional_options:
            source, handled = _apply_file_over_file_optional(
                args, source, destination, src_size, dst_size, option
            )
            if handled:
                break
        else:
            source, destination = _apply_file_over_file_required(
                args, source, destination, src_size, dst_size, option
            )
    return source, destination


def _clobber_existing_folder(args, source, destination, orig_destination):
    log.info("File Over Folder conflict\t%s\t%s", source, destination)
    actions = {
        arggroups.FileOverFolder.SKIP: lambda: (None, destination),
        arggroups.FileOverFolder.RENAME_SRC: lambda: (source, alt_name(destination)),
        arggroups.FileOverFolder.RENAME_DEST: lambda: (source, _rename_destination(args, destination)),
        arggroups.FileOverFolder.DELETE_SRC: lambda: (_delete_source(args, source), destination),
        arggroups.FileOverFolder.DELETE_DEST: lambda: (source, _rmtree_destination(args, destination)),
    }
    if args.file_over_folder == arggroups.FileOverFolder.MERGE:
        nested_destination = os.path.join(destination, path_utils.basename(destination))
        log.info("re-targeted %s -> %s", orig_destination, nested_destination)
        return clobber(args, source, nested_destination)
    return actions[args.file_over_folder]()


def _rmtree_destination(args, destination):
    rmtree(args, destination)
    return destination


def _resolve_folder_over_file(args, source, destination, parent_dir, orig_destination):
    parent_file = parent_dir
    while not os.path.exists(parent_file):
        parent_file = os.path.dirname(parent_file)
        if parent_file == "":
            log.info("Ran out of path from %s", parent_dir)
            raise FileNotFoundError(parent_dir)

    preserve_root(parent_file)
    log.warning("Folder Over File conflict %s\t%s", source, parent_file)
    if args.folder_over_file == arggroups.FolderOverFile.SKIP:
        source = None
    elif args.folder_over_file == arggroups.FolderOverFile.DELETE_SRC:
        rmtree(args, source)
        source = None
    elif args.folder_over_file == arggroups.FolderOverFile.DELETE_DEST:
        unlink(args, parent_file)
    elif args.folder_over_file == arggroups.FolderOverFile.RENAME_DEST:
        rename(args, parent_file, alt_name(parent_file))
    else:
        nested_destination = os.path.join(parent_file, os.path.basename(parent_file))
        while os.path.exists(nested_destination):
            nested_destination = os.path.join(nested_destination, os.path.basename(parent_file))
        temp_rename = alt_name(parent_file)
        rename(args, parent_file, temp_rename)
        if not args.simulate:
            os.makedirs(parent_dir, exist_ok=True)
        if source == os.path.commonpath([source, destination]):
            return temp_rename, nested_destination
        rename(args, temp_rename, nested_destination)
        if destination == nested_destination:
            log.info("re-targeted %s -> %s", orig_destination, destination)
            return clobber(args, source, destination)
    if source and not args.simulate:
        os.makedirs(parent_dir, exist_ok=True)
    return source, destination


def _clobber_missing_destination(args, source, destination, orig_destination):
    parent_dir = os.path.dirname(destination)
    if parent_dir == "":
        return source, destination
    try:
        os.makedirs(parent_dir, exist_ok=True)
    except (FileExistsError, NotADirectoryError, FileNotFoundError):
        return _resolve_folder_over_file(args, source, destination, parent_dir, orig_destination)
    else:
        log.debug("Nothing to clobber %s\t%s", source, destination)
    return source, destination


def clobber(args, source, destination) -> tuple[str | None, str]:
    if source == destination:
        log.info("Destination is the same as source\t%s", destination)
        return None, destination
    if getattr(args, "skip_open", False) and file_utils.is_file_open(source):
        log.info("Source already has an open file handler\t%s", destination)
        return None, destination

    orig_destination = destination
    if os.path.exists(destination):
        if os.path.isdir(destination):
            source, destination = _clobber_existing_folder(args, source, destination, orig_destination)
        else:
            source, destination = _clobber_existing_file(args, source, destination)
    else:
        source, destination = _clobber_missing_destination(args, source, destination, orig_destination)

    if destination != orig_destination:
        log.info("re-targeted %s -> %s", orig_destination, destination)
    return source, destination


def _clobber_new_existing_folder(args, destination, orig_destination):
    log.info("File Over Folder conflict\t%s", destination)
    actions = {
        arggroups.FileOverFolder.SKIP: lambda: destination,
        arggroups.FileOverFolder.RENAME_SRC: lambda: alt_name(destination),
        arggroups.FileOverFolder.RENAME_DEST: lambda: _rename_destination(args, destination),
        arggroups.FileOverFolder.DELETE_DEST: lambda: _rmtree_destination(args, destination),
    }
    if args.file_over_folder == arggroups.FileOverFolder.MERGE:
        nested_destination = os.path.join(destination, path_utils.basename(destination))
        log.info("re-targeted %s -> %s", orig_destination, nested_destination)
        return clobber_new_file(args, nested_destination)
    return actions[args.file_over_folder]()


def _clobber_new_existing_file(args, destination):
    dst_stat = os.stat(destination)
    if dst_stat.st_size == 0:
        log.debug("Overwriting empty file destination %s", destination)
        unlink(args, destination)
        return destination

    log.info("File Over File conflict\t%s", destination)
    optional_options = set(vars(arggroups.FileOverFileOptional).values())
    for option in args.file_over_file:
        log.debug(option)
        if option in optional_options or option == arggroups.FileOverFile.SKIP:
            continue
        if option == arggroups.FileOverFile.DELETE_DEST:
            unlink(args, destination)
        elif option == arggroups.FileOverFile.DELETE_DEST_ASK:
            print(destination)
            if confirm("Overwrite destination file?"):
                unlink(args, destination)
        elif option == arggroups.FileOverFile.RENAME_DEST:
            rename(args, destination, alt_name(destination))
        else:
            destination = alt_name(destination)
    return destination


def _clobber_new_missing_destination(args, destination, orig_destination):
    parent_dir = os.path.dirname(destination)
    if parent_dir == "":
        return destination
    try:
        os.makedirs(parent_dir, exist_ok=True)
    except (FileExistsError, NotADirectoryError, FileNotFoundError):
        parent_file = parent_dir
        while not os.path.exists(parent_file):
            parent_file = os.path.dirname(parent_file)
            if parent_file == "":
                log.info("Ran out of path from %s", parent_dir)
                raise

        preserve_root(parent_file)
        log.warning("Folder Over File conflict %s", parent_file)
        if args.folder_over_file == arggroups.FolderOverFile.DELETE_DEST:
            unlink(args, parent_file)
        elif args.folder_over_file == arggroups.FolderOverFile.RENAME_DEST:
            rename(args, parent_file, alt_name(parent_file))
        else:
            nested_destination = os.path.join(parent_file, os.path.basename(parent_file))
            while os.path.exists(nested_destination):
                nested_destination = os.path.join(nested_destination, os.path.basename(parent_file))
            temp_rename = alt_name(parent_file)
            rename(args, parent_file, temp_rename)
            if not args.simulate:
                os.makedirs(parent_dir, exist_ok=True)
            rename(args, temp_rename, nested_destination)
            if destination == nested_destination:
                log.info("re-targeted %s -> %s", orig_destination, destination)
                return clobber_new_file(args, destination)
        if not args.simulate:
            os.makedirs(parent_dir, exist_ok=True)
    else:
        log.debug("Nothing to clobber %s", destination)
    return destination


def clobber_new_file(args, destination) -> str:
    orig_destination = destination
    if os.path.exists(destination):
        if os.path.isdir(destination):
            destination = _clobber_new_existing_folder(args, destination, orig_destination)
        else:
            destination = _clobber_new_existing_file(args, destination)
    else:
        destination = _clobber_new_missing_destination(args, destination, orig_destination)

    if destination != orig_destination:
        log.info("re-targeted %s -> %s", orig_destination, destination)
    return destination


def prompt(*args, **kwargs) -> str:
    from rich.prompt import Prompt

    clear_input()
    return Prompt.ask(*args, **kwargs)


def set_readline_completion(list_) -> None:
    try:
        import readline
    except ModuleNotFoundError:
        # "Windows not supported"
        return

    def create_completer(list_):
        def list_completer(_text, state):
            line = readline.get_line_buffer()

            if not line:
                min_depth = min([s.count(os.sep) for s in list_]) + 1  # type: ignore
                result_list = [c + " " for c in list_ if c.count(os.sep) <= min_depth]
                random.shuffle(result_list)
                return result_list[:25][state]
            else:
                match_list = [s for s in list_ if s.startswith(line)]
                min_depth = min([s.count(os.sep) for s in match_list]) + 1  # type: ignore
                result_list = [c + " " for c in match_list if c.count(os.sep) <= min_depth]
                random.shuffle(result_list)
                return result_list[:15][state]

        return list_completer

    readline.set_completer(create_completer(list_))
    readline.set_completer_delims("\t")
    readline.parse_and_bind("tab: complete")
    return


def mountpoints():
    import psutil

    mounts = []
    for partition in psutil.disk_partitions():
        if partition.mountpoint in [os.sep, "/var", "/etc", "/usr"] or partition.mountpoint.startswith(
            ("/boot", "/sysroot")
        ):
            continue

        mounts.append(partition.mountpoint)

    return mounts


def get_mount_stats(src_mounts) -> list[dict[str, int | float]]:
    mount_space = []
    total_used = 1
    total_free = 1
    grand_total = 1
    for src_mount in src_mounts:
        total, used, free = shutil.disk_usage(src_mount)
        total_used += used
        total_free += free
        grand_total += total
        mount_space.append((src_mount, used, free, total))

    return [
        {"mount": mount, "used": used / total_used, "free": free / total_free, "total": total / grand_total}
        for mount, used, free, total in mount_space
    ]


def browse(browser, urls):
    for url in urls:
        if not browser or browser in ["echo", "print"]:
            print(url)
        elif browser == "default":
            browsing_success = webbrowser.open(url, new=2, autoraise=False)
            if browsing_success is False:
                log.info("Problem opening %s", url)
        else:
            processes.cmd_detach(*shlex.split(browser), url)

        if len(urls) >= consts.DEFAULT_OPEN_LIMIT:
            time.sleep(1.5)


def cb(data=None):
    if data is None:
        result = subprocess.run(["cb"], stdout=subprocess.PIPE, check=False)
        return result.stdout.decode("utf-8")
    else:
        process = subprocess.Popen(["cb"], stdin=subprocess.PIPE)
        process.communicate(input=data.encode("utf-8"))
        return None
