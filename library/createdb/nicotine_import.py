import argparse, json, os
from pathlib import Path

from library.mediadb import db_media, db_playlists
from library.utils import arggroups, argparse_utils, nums
from library.utils.objects import traverse_obj

USAGE = {
    'nicotine_import': """library database import nicotine DATABASE PATH ...

    Load records from Nicotine+ File Lists

        library database import nicotine ~/lb/soulseek.db /home/xk/.local/share/nicotine/usershares/*

    By default we track deletions when only one file list is specified

        library database import nicotine ~/lb/soulseek.db /home/xk/.local/share/nicotine/usershares/user1
        Marking 508387 orphaned metadata records as deleted

        library database import nicotine ~/lb/soulseek.db /home/xk/.local/share/nicotine/usershares/user2
        Marking 31862 metadata records as undeleted
        Marking 216495 orphaned metadata records as deleted

        If this is undesirable, pass the `--no-track-deleted` flag
""",
}


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=USAGE['nicotine_import'])
    parser.add_argument("--track-deleted", default=True, action=argparse.BooleanOptionalAction)
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=True)

    return args


def from_nicotine_file_list_to_records(data):
    result = []
    for entry in data:
        path = entry[0].replace("\\", os.sep)
        for song in entry[1]:
            song_info = {
                "path": f"{path}/{song[1]}",
                "size": song[2],
                "duration": nums.safe_int(traverse_obj(song, (4, "1"))),
            }
            result.append(song_info)

    return result


def nicotine_import() -> None:
    args = parse_args()

    db_playlists.create(args)
    db_media.create(args)

    for path in args.paths:
        file_stats = Path(path).stat()
        time_created = int(file_stats.st_mtime) or int(file_stats.st_ctime)

        with open(path) as fp:
            data = json.load(fp)

        data = from_nicotine_file_list_to_records(data)
        data = [d | {"time_created": time_created, "time_deleted": 0} for d in data]

        db_media.update_media(args, data, mark_deleted=args.track_deleted and len(args.paths) == 1)
