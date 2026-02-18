import os

from library import usage
from library.playback import media_printer
from library.utils import (
    arggroups,
    argparse_utils,
    filter_engine,
    iterables,
    processes,
    shell_utils,
    sqlgroups,
    strings,
)


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


def get_data(args) -> list[dict]:
    filter_engine_obj = filter_engine.FilterEngine(args)

    def fs_gen(args):
        if args.hide_deleted:
            args.paths = [p for p in args.paths if os.path.exists(p)]
        return shell_utils.gen_d(args)

    files = filter_engine_obj.get_filtered_data(
        db_sql_func=lambda a: sqlgroups.fs_sql(a, limit=None),
        fs_gen_func=fs_gen,
    )
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
