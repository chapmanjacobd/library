import os, re

from library import usage
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, consts, file_utils, iterables, processes, sqlgroups, strings


def parse_args(defaults_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage.files_info)
    arggroups.files(parser)
    arggroups.sql_fs(parser)
    parser.set_defaults(hide_deleted=True)

    arggroups.debug(parser)

    arggroups.database_or_paths(parser)
    parser.set_defaults(**(defaults_override or {}))
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.files_post(args)
    arggroups.sql_fs_post(args)

    return args


def is_mime_match(types, mime_type):
    # exact match
    for type_ in types:
        is_match = mime_type == type_
        if is_match:
            return True

    # substring match
    mime_type = mime_type.replace("<", "").replace(">", "")
    mime_type_words = [word for word in re.split(r"[ /]+", mime_type) if word]

    if not mime_type_words:
        return False

    for type_ in types:
        is_case_sensitive = not type_.islower()

        for word in mime_type_words:
            is_match = word == type_ if is_case_sensitive else word.lower() == type_.lower()
            if is_match:
                return True

    return False


def filter_mimetype(args, files):
    if args.type or args.no_type:
        files = [d if "type" in d else file_utils.get_file_type(d) for d in files]
    if args.no_type:
        files = [d for d in files if not is_mime_match(args.no_type, d["type"] or "None")]
    if args.type:
        files = [d for d in files if is_mime_match(args.type, d["type"] or "None")]

    return files


def filter_files_by_criteria(args, files):
    if "sizes" not in args.defaults:
        size_exists, files = iterables.peek_value_exists(files, "size")
        if not size_exists:
            files = file_utils.get_files_stats(files)
        files = [d for d in files if args.sizes(d["size"])]

    files = filter_mimetype(args, files)

    if getattr(args, "time_created", []):
        files = [d if "time_created" in d else file_utils.get_file_stats(d) for d in files]
        files = [
            d
            for d in files
            if d["time_created"] > 0 and args.time_created(consts.APPLICATION_START - d["time_created"])  # type: ignore
        ]
    if getattr(args, "time_modified", []):
        files = [d if "time_modified" in d else file_utils.get_file_stats(d) for d in files]
        files = [
            d
            for d in files
            if d["time_modified"] > 0 and args.time_modified(consts.APPLICATION_START - d["time_modified"])  # type: ignore
        ]

    if args.to_json:
        files = [d if "size" in d else file_utils.get_file_stats(d) for d in files]
        files = [d if "type" in d else file_utils.get_file_type(d) for d in files]

    return list(files)


def get_data(args) -> list[dict]:
    if args.database:
        files = list(args.db.query(*sqlgroups.fs_sql(args, limit=None)))
        files = filter_mimetype(args, files)
    else:
        if args.hide_deleted:
            args.paths = [p for p in args.paths if os.path.exists(p)]
        files = file_utils.gen_d(args)

        files = filter_files_by_criteria(args, files)

    if not files:
        processes.no_media_found()
    return files


def files_info(defaults_override=None):
    args = parse_args(defaults_override)
    files = get_data(args)

    if not files:
        processes.no_media_found()

    summary = iterables.list_dict_summary(files)

    media_printer.media_printer(args, files, units="files")
    if not args.to_json:
        for d in summary:
            if "count" in d:
                print(f"{d['path']}={strings.file_size(d['size'])} count={d['count']}")
