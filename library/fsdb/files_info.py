import os, re
from random import random

from library import usage
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, consts, file_utils, iterables, processes, sqlgroups, strings
from library.utils.objects import Reverser


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


def eval_sql_expr(key, op, val, item):
    """Evaluate a simplified SQL-like operator expression on item."""
    col_val = item.get(key)

    if op == "LIKE":
        # SQLite LIKE -> translate %/_ to regex
        regex = "^" + re.escape(val.strip('"')).replace("%", ".*").replace("_", ".") + "$"
        return bool(re.match(regex, str(col_val or "")))
    elif op == "IS" and val.upper() == "NULL":
        return col_val is None
    elif op in ("=", "=="):
        return col_val == val.strip('"')
    elif op in ("!=", "<>"):
        return col_val != val.strip('"')
    elif op == ">":
        return col_val > val.strip('"')
    elif op == "<":
        return col_val < val.strip('"')
    elif op == ">=":
        return col_val >= val.strip('"')
    elif op == "<=":
        return col_val <= val.strip('"')
    else:
        msg = f"Unsupported operator: {op}"
        raise ValueError(msg)


def sort_files_by_criteria(args, files):
    def normalize_key(key: str) -> str:
        """Remove table prefixes like m.path -> path."""
        return key.split(".")[-1]

    def get_sort_key(item):
        sort_values = []
        for s in args.sort.split(","):
            parts = s.strip().split()
            reverse = parts[-1].lower() == "desc"
            key = normalize_key(parts[0])

            if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() in ("asc", "desc")):
                # simple column
                if key.lower() == "random()":
                    value = random()
                else:
                    value = item.get(key)
            else:
                # operator form: col OP val [ASC|DESC]
                op = parts[1].upper()
                val = " ".join(parts[2:-1]) if reverse else " ".join(parts[2:])
                value = eval_sql_expr(key, op, val, item)

            if value is None:
                value = "" if isinstance(item.get("path"), str) else 0

            sort_values.append(Reverser(value) if reverse else value)

        return tuple(sort_values)

    return sorted(files, key=get_sort_key)


def filter_files_by_criteria(args, files):
    if "sizes" not in args.defaults:
        size_exists, files = iterables.peek_value_exists(files, "size")
        if not size_exists:
            files = file_utils.get_files_stats(files)
        files = [d for d in files if args.sizes(d["size"])]
    elif "size" in getattr(args, "sort", []):
        size_exists, files = iterables.peek_value_exists(files, "size")
        if not size_exists:
            files = file_utils.get_files_stats(files)

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

    if files and getattr(args, "sort", []):
        files = sort_files_by_criteria(args, files)

    if files and getattr(args, "limit", []):
        files = files[: args.limit]

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
