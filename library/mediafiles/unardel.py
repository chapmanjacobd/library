import argparse, concurrent.futures, os
from shutil import which

from library import usage
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    devices,
    file_utils,
    filter_engine,
    iterables,
    path_utils,
    printing,
    processes,
    shell_utils,
    strings,
)
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.unardel)
    arggroups.files(parser, no_db=True)

    parser.add_argument("--continue-from", help="Skip media until specific file path is seen")
    parser.add_argument("--move", help="Directory to move successful files")
    parser.add_argument("--move-broken", help="Directory to move unsuccessful files")

    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.files_post(args)

    return args


def collect_media(args) -> list[dict]:
    UNAR_INSTALLED = which("lsar")

    if not UNAR_INSTALLED:
        processes.exit_error("unar not installed. Archives will not be extracted")

    media = shell_utils.gen_d(args, consts.ARCHIVE_EXTENSIONS)

    media = filter_engine.filter_items_by_criteria(args, media)
    media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]
    return media


def check_shrink(args, m) -> list:
    m["ext"] = path_utils.ext(m["path"])
    filetype = (m.get("type") or "").lower()

    if not m["size"]:  # empty or deleted file
        return []

    if m.get("compressed_size"):
        return [m]
    elif (filetype and (filetype.startswith("archive/") or filetype.endswith("+zip") or " archive" in filetype)) or m[
        "ext"
    ] in consts.ARCHIVE_EXTENSIONS:
        contents = processes.lsar(m["path"])
        return [check_shrink(args, d) for d in contents]
    else:
        log.warning("[%s]: Skipping unknown filetype %s %s", m["path"], m["ext"], filetype)
    return []


def replace_media_paths(media, path_updates):
    updated_media = []
    for item in media:
        path = os.fspath(item["path"])
        seen_paths = {path}
        applied_updates = set()
        while True:
            matches = [
                (index, update)
                for index, update in enumerate(path_updates)
                if index not in applied_updates
                and (
                    path == os.fspath(update["path"])
                    or path.startswith(os.fspath(update["path"]).rstrip(os.sep) + os.sep)
                )
            ]
            if not matches:
                break

            index, match = max(matches, key=lambda pair: len(os.fspath(pair[1]["path"])))
            update_path = os.fspath(match["path"])
            new_path = os.fspath(match["new_path"]) + path[len(update_path) :]
            if new_path in seen_paths:
                break
            applied_updates.add(index)
            path = new_path
            seen_paths.add(path)
        updated_media.append({**item, "path": path} if path != item["path"] else item)
    return updated_media


def _extracted_media(output_paths, existing_paths, path_updates):
    media = []
    for output_path, source_archive in output_paths:
        if os.path.abspath(output_path) == os.path.dirname(os.path.abspath(source_archive)):
            paths = [
                update["new_path"]
                for update in path_updates
                if os.path.isfile(update["new_path"])
            ]
        else:
            paths = processes.iter_regular_files(output_path)

        for path in paths:
            if path in existing_paths or processes.is_archive_path(path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            media.append(
                {
                    "path": path,
                    "size": size,
                    "compressed_size": 0,
                    "ext": path_utils.ext(path),
                }
            )
            existing_paths.add(path)
    return media


def unardel() -> None:
    args = parse_args()
    media = collect_media(args)

    mp_args = argparse.Namespace(**{k: v for k, v in args.__dict__.items() if k != "db"})
    with concurrent.futures.ThreadPoolExecutor() as executor:  # for lsar
        futures = {executor.submit(check_shrink, mp_args, m) for m in media}
    media = iterables.conform(v.result() for v in futures)

    media = sorted(media, key=lambda d: d["compressed_size"])

    if args.continue_from:
        media = iterables.tail_from(media, args.continue_from, key="path")

    media = iterables.list_dict_unique(media, ["path"])

    if not media:
        processes.no_media_found()

    summary = {}
    for m in media:
        media_key = m["ext"]
        if m.get("compressed_size"):
            media_key += " (archived)"

        if media_key not in summary:
            summary[media_key] = {
                "count": 0,
                "compressed_size": 0,
                "extracted_size": 0,
            }
        summary[media_key]["count"] += 1
        summary[media_key]["extracted_size"] += m["size"]
        summary[media_key]["compressed_size"] += m.get("compressed_size") or 0

    summary = [{"media_key": k, **v} for k, v in summary.items()]
    compressed_size = sum([m["compressed_size"] for m in summary])
    extracted_size = sum([m["extracted_size"] for m in summary])

    summary = sorted(summary, key=lambda d: d["extracted_size"] / d["compressed_size"])
    summary = iterables.list_dict_filter_bool(summary, keep_0=False)

    for t in ["compressed_size", "extracted_size"]:
        summary = printing.col_filesize(summary, t)
    printing.table(summary)
    print()

    print("Compressed size:", strings.file_size(compressed_size))
    print("Extracted size:", strings.file_size(extracted_size))

    uncompressed_archives = set()
    new_free_space = 0
    if args.no_confirm or devices.confirm("Proceed?"):
        path_updates = []
        extracted_outputs = []
        for m in media:
            if (
                m.get("compressed_size")
                and os.path.exists(m["archive_path"])
                and m["archive_path"] not in uncompressed_archives
            ):
                uncompressed_archives.add(m["archive_path"])

                if args.simulate:
                    log.info("Unarchiving %s", m["archive_path"])
                else:
                    output_path, updates = processes.extract_nested_archives(
                        m["archive_path"],
                        single_file_flatten=True,
                    )
                    extracted_outputs.append((output_path, m["archive_path"]))
                    path_updates.extend(updates)

        original_media_paths = {m["path"] for m in media}
        media = replace_media_paths(media, path_updates)
        existing_paths = {m["path"] for m in media} | original_media_paths
        media.extend(_extracted_media(extracted_outputs, existing_paths, path_updates))
        media = [
            m
            for m in media
            if not (
                m.get("compressed_size")
                and processes.is_archive_path(m["path"])
            )
        ]
        media = iterables.list_dict_unique(media, ["path"])

        for m in media:
            log.info(
                "%s freed. Processing %s (%s)",
                strings.file_size(new_free_space),
                m["path"],
                strings.file_size(m["size"]),
            )

            if not os.path.exists(m["path"]):
                log.error("[%s]: FileNotFoundError", m["path"])
                m["time_deleted"] = consts.APPLICATION_START

            if args.move and not m.get("time_deleted"):
                dest = path_utils.relative_from_mountpoint(m["path"], args.move)
                if args.simulate:
                    shell_utils.rename_move_file(m["path"], dest, simulate=True)
                else:
                    shell_utils.rename_move_file(m["path"], dest)
            elif args.move_broken and m.get("time_deleted") and os.path.exists(m["path"]):
                dest = path_utils.relative_from_mountpoint(m["path"], args.move_broken)
                if args.simulate:
                    shell_utils.rename_move_file(m["path"], dest, simulate=True)
                else:
                    shell_utils.rename_move_file(m["path"], dest)
