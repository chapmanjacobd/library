import argparse, json, os
from pathlib import Path

from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils, devices, file_utils, printing
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library merge-folders", usage=usage.merge_folders)
    arggroups.clobber(parser)
    arggroups.simulate(parser)
    arggroups.debug(parser)

    parser.add_argument("sources", nargs="+")
    parser.add_argument("destination")
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    args.destination = arg_utils.split_folder_glob(args.destination)

    return args


def existing_stats(root_folder, root_glob):
    prefix = f"{root_folder}{os.sep}{root_glob}"

    files: set[Path] = set()
    folders: set[Path] = set()
    for idx, item in enumerate(root_folder.rglob(root_glob)):
        if item.is_dir():
            folders.add(item)
        else:
            files.add(item)

        if idx % 15 == 0:
            printing.print_overwrite(f"[{prefix}] Files: {len(files)} Folders: {len(folders)}")

    file_folders = {p.parent for p in files}
    no_file_folders = folders - file_folders

    parents = {p.parent.parent for p in files} | {p.parent for p in no_file_folders}
    folder_folders = no_file_folders & parents
    empty_folders = no_file_folders - folder_folders

    # assert all(list(p.glob('*')) != [] for p in folder_folders)
    # assert all(list(p.glob('*')) == [] for p in empty_folders)

    print(
        f"\r[{prefix}] Files: {len(files)} "
        f"Folders: [{len(file_folders)} from files, {len(folder_folders)} from folders, {len(empty_folders)} empty]",
        flush=True,
    )

    return files, {"file": file_folders, "folder": folder_folders, "empty": empty_folders}


def gen_rename_data(destination_folder, destination_files, source_folder, source_files):
    source_rename_data = []
    for source_file in source_files:
        renamed_file = destination_folder / source_file.relative_to(source_folder)
        is_conflict = renamed_file in destination_files
        if is_conflict:
            log.info("%s conflicts with %s", source_file, renamed_file)
        else:
            log.debug("%s can be renamed cleanly to %s", source_file, renamed_file)
        source_rename_data.append((is_conflict, source_file, renamed_file))
    return source_rename_data


def get_clobber(args):
    choice = None
    if args.replace is not None:
        choice = "replace" if args.replace else "no-replace"
    else:
        choice = devices.prompt(choices=["replace", "no-replace", "simulate-replace", "quit"])

    if choice == "quit":
        raise SystemExit(130)
    if choice == "simulate-replace":
        args.simulate = True
        choice = "replace"

    assert choice in ["replace", "no-replace"]
    return choice == "replace"


def apply_merge(args, empty_folder_data, rename_data, clobber):
    def print_mv(t):
        if t[0]:  ## file exists in destination already
            if not clobber:
                log.info("[%s]: Skipping due to existing file %s", t[1], t[2])
            else:
                printing.pipe_print("mv", t[1], t[2])
        else:
            printing.pipe_print("mv", t[1], t[2])

    def mv(t):
        mv_fn = os.renames
        if t[0]:  ## file exists in destination already
            mv_fn = os.replace
            if not clobber:
                log.info("[%s]: Skipping due to existing file %s", t[1], t[2])
                return
        try:
            mv_fn(t[1], t[2])
        except Exception:
            file_utils.rename_move_file(t[1], t[2])

    if args.simulate:
        for p in empty_folder_data:
            print("mkdir", p)

        for t in rename_data:
            print_mv(t)
    else:
        for p in empty_folder_data:
            p.mkdir(parents=True, exist_ok=True)

        for t in rename_data:
            try:
                mv(t)
            except (NotADirectoryError, FileExistsError):
                log.error("Folder %s not moved because target is a file with the same name %s", t[1], t[2])
                log.error("\tSuggested action: mv %s %s_folder", t[1], t[2])
            except IsADirectoryError:
                log.error("File %s not moved because target is a folder with the same name %s", t[1], t[2])
                log.error("\tSuggested action: mv %s %s.txt", t[1], t[2])
            except OSError as e:
                if (getattr(e, "winerror", None) or 0) == 87:
                    log.error("File %s not moved because target is a folder with the same name %s", t[1], t[2])
                    log.error("\tSuggested action: mv %s %s.txt", t[1], t[2])
                else:
                    raise e


def merge_folders() -> None:
    args = parse_args()

    print("Destination:")
    destination_folder, destination_glob = args.destination
    destination_folder.mkdir(parents=True, exist_ok=True)
    destination_files, destination_folders_dict = existing_stats(destination_folder, destination_glob)

    destination_folders = (
        destination_folders_dict["file"] | destination_folders_dict["folder"] | destination_folders_dict["empty"]
    )

    all_source_folders = set()
    empty_folder_data: set[Path] = set()
    rename_data: list[tuple[bool, Path, Path]] = []
    clobber = False  # default nothing to clobber; no confirmation prompt
    print("Sources:")
    for source in args.sources:
        source_folder, source_glob = arg_utils.split_folder_glob(source)
        source_files, source_folders_dict = existing_stats(source_folder, source_glob)
        source_folders = source_folders_dict["file"] | source_folders_dict["folder"] | source_folders_dict["empty"]

        source_new_empty_folders = gen_rename_data(
            destination_folder, destination_folders, source_folder, source_folders_dict["empty"]
        )
        source_new_empty_folders = [t for t in source_new_empty_folders if not t[0]]

        source_file_renames = gen_rename_data(destination_folder, destination_files, source_folder, source_files)

        previous_source_renames = [t[2] for t in rename_data]
        trumping_files = [t for t in source_file_renames if t[0] and t[2] in previous_source_renames]

        source_new_file_folders = {t[2].parent for t in source_file_renames if not t[0]} - destination_folders
        conflicts = sum(1 for t in source_file_renames if t[0])
        print(
            f"""Simulated move:
\tNew files: {sum(1 for t in source_file_renames if not t[0])}
\tConflicts: {conflicts}
\tTrumps: {len(trumping_files)}
\tNew folders from files: {len(source_new_file_folders)}
\tNew empty folders: {len(source_new_empty_folders)} """
        )

        if conflicts:
            clobber = None
        if trumping_files:
            clobber = None
            log.info("Trumped files found:")
            for trumping_tuple in trumping_files:
                trumped_files = [str(t[1]) for t in rename_data if t[2] == trumping_tuple[2]]
                log.info(
                    "\t%s would replace earlier move from source(s) %s", trumping_tuple[1], json.dumps(trumped_files)
                )

        empty_folder_data |= {t[2] for t in source_new_empty_folders}
        rename_data.extend(source_file_renames)
        destination_folders |= {destination_folder / p.relative_to(source_folder) for p in source_folders}
        all_source_folders |= source_folders
        print()

    if clobber is None:
        clobber = get_clobber(args)

    apply_merge(args, empty_folder_data, rename_data, clobber=clobber)

    for f in sorted((str(p) for p in all_source_folders), key=len, reverse=True):
        try:
            os.removedirs(f)
        except OSError:
            pass


if __name__ == "__main__":
    merge_folders()
