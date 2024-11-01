import os, random, shlex, shutil, sys, time, webbrowser

from xklb.files import sample_compare
from xklb.utils import arggroups, consts, file_utils, path_utils, processes, strings
from xklb.utils.log_utils import log

webbrowser.register("termux-open-url '%s'", None)


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


class InteractivePrompt(Exception):
    pass


def confirm(*args, **kwargs) -> bool:
    from rich.prompt import Confirm

    if consts.PYTEST_RUNNING:
        raise InteractivePrompt

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
            log.info("File Over Folder conflict\t%s\t%s", source, destination)
            match args.file_over_folder:
                case arggroups.FileOverFolder.SKIP:
                    source = None
                case arggroups.FileOverFolder.RENAME_SRC:
                    destination = file_utils.alt_name(destination)
                case arggroups.FileOverFolder.RENAME_DEST:
                    existing_rename = file_utils.alt_name(destination)
                    rename(args, destination, existing_rename)
                case arggroups.FileOverFolder.DELETE_SRC:
                    unlink(args, source)
                    source = None
                case arggroups.FileOverFolder.DELETE_DEST:
                    rmtree(args, destination)
                case arggroups.FileOverFolder.MERGE:
                    destination = os.path.join(destination, path_utils.basename(destination))  # down
                    log.info("re-targeted %s -> %s", orig_destination, destination)
                    return clobber(args, source, destination)

        else:
            src_stat = os.stat(source)
            dst_stat = os.stat(destination)
            if os.path.samestat(src_stat, dst_stat):
                log.info("Destination is the same as source\t%s", destination)
                return None, destination

            src_size = src_stat.st_size
            dst_size = dst_stat.st_size

            if dst_size == 0:
                log.debug("Overwriting empty file destination %s\t%s", source, destination)
                unlink(args, destination)
                return source, destination

            log.info("File Over File conflict\t%s\t%s", source, destination)
            for s in args.file_over_file:
                log.debug(s)
                match s:
                    case arggroups.FileOverFileOptional.DELETE_DEST_HASH:
                        if sample_compare.sample_cmp(source, destination, ignore_holes=True):
                            unlink(args, destination)
                            break
                    case arggroups.FileOverFileOptional.DELETE_DEST_SIZE:
                        if src_size == dst_size:
                            unlink(args, destination)
                            break
                    case arggroups.FileOverFileOptional.DELETE_DEST_LARGER:
                        if src_size < dst_size:
                            unlink(args, destination)
                            break
                    case arggroups.FileOverFileOptional.DELETE_DEST_SMALLER:
                        if src_size > dst_size:
                            unlink(args, destination)
                            break
                    case arggroups.FileOverFileOptional.DELETE_SRC_HASH:
                        if sample_compare.sample_cmp(source, destination, ignore_holes=True):
                            unlink(args, source)
                            source = None
                            break
                    case arggroups.FileOverFileOptional.DELETE_SRC_SIZE:
                        if src_size == dst_size:
                            unlink(args, source)
                            source = None
                            break
                    case arggroups.FileOverFileOptional.DELETE_SRC_LARGER:
                        if src_size > dst_size:
                            unlink(args, source)
                            source = None
                            break
                    case arggroups.FileOverFileOptional.DELETE_SRC_SMALLER:
                        if src_size < dst_size:
                            unlink(args, source)
                            source = None
                            break
                    case arggroups.FileOverFileOptional.SKIP_HASH:
                        if sample_compare.sample_cmp(source, destination, ignore_holes=True):
                            source = None
                            break
                    case arggroups.FileOverFile.SKIP:
                        source = None
                    case arggroups.FileOverFile.DELETE_DEST:
                        unlink(args, destination)
                    case arggroups.FileOverFile.DELETE_DEST_ASK:
                        print(source)
                        print("  -->", destination)
                        log_size_diff(src_size, dst_size)
                        if confirm("Replace destination file?"):
                            unlink(args, destination)
                    case arggroups.FileOverFile.RENAME_SRC:
                        destination = file_utils.alt_name(destination)
                    case arggroups.FileOverFile.RENAME_DEST:
                        existing_rename = file_utils.alt_name(destination)
                        rename(args, destination, existing_rename)
                    case arggroups.FileOverFile.DELETE_SRC:
                        unlink(args, source)
                        source = None

    else:
        parent_dir = os.path.dirname(destination)
        if parent_dir == "":  # relative file
            return source, destination

        try:
            os.makedirs(parent_dir, exist_ok=True)
        except (
            FileExistsError,
            NotADirectoryError,  # a file exists _somewhere_ in the path hierarchy
            FileNotFoundError,  # Windows
        ):
            parent_file = parent_dir
            while not os.path.exists(parent_file):  # until we find the file conflict
                parent_file = os.path.dirname(parent_file)  # up
                if parent_file == "":
                    log.info("Ran out of path from %s", parent_dir)
                    raise

            preserve_root(parent_file)

            log.warning("Folder Over File conflict %s\t%s", source, parent_file)
            match args.folder_over_file:
                case arggroups.FolderOverFile.SKIP:
                    source = None
                case arggroups.FolderOverFile.DELETE_SRC:
                    rmtree(args, source)
                    source = None
                case arggroups.FolderOverFile.DELETE_DEST:
                    unlink(args, parent_file)
                case arggroups.FolderOverFile.RENAME_DEST:
                    existing_rename = file_utils.alt_name(parent_file)
                    rename(args, parent_file, existing_rename)
                case arggroups.FolderOverFile.MERGE:
                    temp_rename = file_utils.alt_name(parent_file)
                    rename(args, parent_file, temp_rename)
                    os.makedirs(parent_dir, exist_ok=True)  # there can't be more than one blocking file

                    while os.path.exists(parent_file):  # until we find an open file slot
                        parent_file = os.path.join(parent_file, os.path.basename(parent_file))  # down

                    if source == os.path.commonpath([source, destination]):
                        # file was a conflict with destination path but let the caller rename it
                        return temp_rename, parent_file
                    rename(args, temp_rename, parent_file)  # temporary rename to final dest
                    if destination == parent_file:
                        log.info("re-targeted %s -> %s", orig_destination, destination)
                        return clobber(args, source, destination)

            if source:
                os.makedirs(parent_dir, exist_ok=True)  # original destination parent
        else:
            log.debug("Nothing to clobber %s\t%s", source, destination)

    if destination != orig_destination:
        log.info("re-targeted %s -> %s", orig_destination, destination)

    return source, destination


def clobber_new_file(args, destination) -> str:
    orig_destination = destination

    if os.path.exists(destination):
        if os.path.isdir(destination):
            log.info("File Over Folder conflict\t%s", destination)
            match args.file_over_folder:
                case arggroups.FileOverFolder.SKIP:
                    pass
                case arggroups.FileOverFolder.RENAME_SRC:
                    destination = file_utils.alt_name(destination)
                case arggroups.FileOverFolder.RENAME_DEST:
                    existing_rename = file_utils.alt_name(destination)
                    rename(args, destination, existing_rename)
                case arggroups.FileOverFolder.DELETE_DEST:
                    rmtree(args, destination)
                case _:  # FileOverFolder.MERGE
                    destination = os.path.join(destination, path_utils.basename(destination))  # down
                    log.info("re-targeted %s -> %s", orig_destination, destination)
                    return clobber_new_file(args, destination)

        else:
            dst_stat = os.stat(destination)
            dst_size = dst_stat.st_size

            if dst_size == 0:
                log.debug("Overwriting empty file destination %s", destination)
                unlink(args, destination)
                return destination

            log.info("File Over File conflict\t%s", destination)
            for s in args.file_over_file:
                log.debug(s)
                match s:
                    case arggroups.FileOverFile.SKIP:
                        pass

                    case arggroups.FileOverFileOptional.DELETE_DEST_HASH:
                        pass
                    case arggroups.FileOverFileOptional.DELETE_DEST_SIZE:
                        pass
                    case arggroups.FileOverFileOptional.DELETE_DEST_LARGER:
                        pass
                    case arggroups.FileOverFileOptional.DELETE_DEST_SMALLER:
                        pass
                    case arggroups.FileOverFileOptional.DELETE_SRC_HASH:
                        pass
                    case arggroups.FileOverFileOptional.DELETE_SRC_SIZE:
                        pass
                    case arggroups.FileOverFileOptional.DELETE_SRC_LARGER:
                        pass
                    case arggroups.FileOverFileOptional.DELETE_SRC_SMALLER:
                        pass
                    case arggroups.FileOverFileOptional.SKIP_HASH:
                        pass

                    case arggroups.FileOverFile.DELETE_DEST:
                        unlink(args, destination)
                    case arggroups.FileOverFile.DELETE_DEST_ASK:
                        print(destination)
                        if confirm("Overwrite destination file?"):
                            unlink(args, destination)
                    case arggroups.FileOverFile.RENAME_DEST:
                        existing_rename = file_utils.alt_name(destination)
                        rename(args, destination, existing_rename)
                    case _:  # FileOverFile.RENAME_SRC
                        destination = file_utils.alt_name(destination)

    else:
        parent_dir = os.path.dirname(destination)
        if parent_dir == "":  # relative file
            return destination

        try:
            os.makedirs(parent_dir, exist_ok=True)
        except (
            FileExistsError,
            NotADirectoryError,  # a file exists _somewhere_ in the path hierarchy
            FileNotFoundError,  # Windows
        ):
            parent_file = parent_dir
            while not os.path.exists(parent_file):  # until we find the file conflict
                parent_file = os.path.dirname(parent_file)  # up
                if parent_file == "":
                    log.info("Ran out of path from %s", parent_dir)
                    raise

            preserve_root(parent_file)

            log.warning("Folder Over File conflict %s", parent_file)
            match args.folder_over_file:
                case arggroups.FolderOverFile.DELETE_DEST:
                    unlink(args, parent_file)
                case arggroups.FolderOverFile.RENAME_DEST:
                    existing_rename = file_utils.alt_name(parent_file)
                    rename(args, parent_file, existing_rename)
                case _:  # FolderOverFile.MERGE
                    temp_rename = file_utils.alt_name(parent_file)
                    rename(args, parent_file, temp_rename)
                    os.makedirs(parent_dir, exist_ok=True)  # there can't be more than one blocking file

                    while os.path.exists(parent_file):  # until we find an open file slot
                        parent_file = os.path.join(parent_file, os.path.basename(parent_file))  # down

                    rename(args, temp_rename, parent_file)  # temporary rename to final dest
                    if destination == parent_file:
                        log.info("re-targeted %s -> %s", orig_destination, destination)
                        return clobber_new_file(args, destination)

            os.makedirs(parent_dir, exist_ok=True)  # original destination parent
        else:
            log.debug("Nothing to clobber %s", destination)

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
        elif browser in ["default"]:
            browsing_success = webbrowser.open(url, new=2, autoraise=False)
            if browsing_success is False:
                log.info("Problem opening %s", url)
        else:
            processes.cmd_detach(*shlex.split(browser), url)

        if len(urls) >= consts.MANY_LINKS:
            time.sleep(1.5)
