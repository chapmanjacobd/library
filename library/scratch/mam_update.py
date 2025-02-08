import json

from library.mediadb import db_playlists
from library.scratch.mam_search import mam_update_playlist
from library.utils import arg_utils, arggroups, argparse_utils, web
from library.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser()
    parser.add_argument("--base-url", default="https://www.myanonamouse.net")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--cookie", required=True)
    arggroups.requests(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    web.requests_session(args)  # prepare requests session
    return args


def mam_update():
    args = parse_args()

    mam_playlists = db_playlists.get_all(
        args, "id, path, extractor_config", sql_filters=["AND extractor_key = 'MAMSearch'"]
    )
    for playlist in mam_playlists:
        extractor_config = json.loads(playlist["extractor_config"])
        args_env = arg_utils.override_config(args, extractor_config)
        args_env.playlists_id = playlist["id"]

        new_media = mam_update_playlist(args_env, playlist["path"])
        log.info("Saved %s new media", new_media)
        if new_media > 0:
            db_playlists.update_more_frequently(args, playlist["path"])
        else:
            db_playlists.update_less_frequently(args, playlist["path"])

        web.sleep(args, secs=2)


if __name__ == "__main__":
    mam_update()
