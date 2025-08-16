import argparse, concurrent.futures, os
from shutil import which

from library import usage
from library.fsdb import files_info
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    devices,
    file_utils,
    iterables,
    path_utils,
    printing,
    processes,
    strings,
)
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.unardel)
    arggroups.files(parser, no_db=True)

    parser.add_argument("--continue-from", help="Skip media until specific file path is seen")
    parser.add_argument("--move", help="Directory to move successful files")
    parser.add_argument("--move-broken", help="Directory to move unsuccessful files")

    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=False, help="Clean output path")

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

    media = file_utils.gen_d(args, consts.ARCHIVE_EXTENSIONS)

    media = files_info.filter_files_by_criteria(args, media)
    media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]
    return media


def check_shrink(args, m) -> list:
    m["ext"] = path_utils.ext(m["path"])
    filetype = (m.get("type") or "").lower()

    if not m["size"]:  # empty or deleted file
        return []

    if (filetype and (filetype.startswith("archive/") or filetype.endswith("+zip") or " archive" in filetype)) or m[
        "ext"
    ] in consts.ARCHIVE_EXTENSIONS:
        contents = processes.lsar(m["path"])
        return [check_shrink(args, d) for d in contents]
    elif m.get("compressed_size"):
        return [m]
    else:
        log.warning("[%s]: Skipping unknown filetype %s %s", m["path"], m["ext"], filetype)
    return []


def unardel() -> None:
    args = parse_args()
    media = collect_media(args)

    mp_args = argparse.Namespace(**{k: v for k, v in args.__dict__.items() if k not in {"db"}})
    with concurrent.futures.ThreadPoolExecutor() as executor:  # for lsar
        futures = {executor.submit(check_shrink, mp_args, m) for m in media}
    media = iterables.conform(v.result() for v in futures)

    media = sorted(media, key=lambda d: d["compressed_size"])

    if args.continue_from:
        media = iterables.tail_from(media, args.continue_from, key="path")

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
        for m in media:
            log.info(
                "%s freed. Processing %s (%s)",
                strings.file_size(new_free_space),
                m["path"],
                strings.file_size(m["size"]),
            )

            if m.get("compressed_size"):
                if os.path.exists(m["archive_path"]):
                    if m["archive_path"] in uncompressed_archives:
                        continue
                    uncompressed_archives.add(m["archive_path"])

                    if args.simulate:
                        log.info("Unarchiving %s", m["archive_path"])
                    else:
                        processes.unar_delete(m["archive_path"])

                if not os.path.exists(m["path"]):
                    log.error("[%s]: FileNotFoundError from archive %s", m["path"], m["archive_path"])
                    continue
            else:
                if not os.path.exists(m["path"]):
                    log.error("[%s]: FileNotFoundError", m["path"])
                    m["time_deleted"] = consts.APPLICATION_START
                    continue

                if args.move and not m.get("time_deleted") and m.get("new_path"):
                    dest = path_utils.relative_from_mountpoint(m["new_path"], args.move)
                    file_utils.rename_move_file(m["new_path"], dest)
                elif args.move_broken and not m.get("time_deleted") and os.path.exists(m["path"]):
                    dest = path_utils.relative_from_mountpoint(m["path"], args.move_broken)
                    file_utils.rename_move_file(m["path"], dest)
