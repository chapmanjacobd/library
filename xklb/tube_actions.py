from pathlib import Path

from xklb.fs_actions import parse_args, process_actions
from xklb.utils import CAST_NOW_PLAYING, Subcommand

# TODO: add cookiesfrombrowser: ('firefox', ) as a default
# cookiesfrombrowser: ('vivaldi', ) # should not crash if not installed ?

default_ydl_opts = {
    # "writesubtitles": True,
    # "writeautomaticsub": True,
    # "subtitleslangs": "en.*,EN.*",
    "lazy_playlist": True,
    "skip_download": True,
    "force_write_download_archive": True,
    "check_formats": False,
    "no_check_certificate": True,
    "no_warnings": True,
    "ignore_no_formats_error": True,
    "ignoreerrors": "only_download",
    "skip_playlist_after_errors": 20,
    "quiet": True,
    "dynamic_mpd": False,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "extract_flat": True,
    "clean_infojson": False,
    "playlistend": 20000,
    "rejecttitle": "|".join(
        [
            "Trailer",
            "Sneak Peek",
            "Preview",
            "Teaser",
            "Promo",
            "Crypto",
            "Montage",
            "Bitcoin",
            "Apology",
            " Clip",
            "Clip ",
            "Best of",
            "Compilation",
            "Top 10",
            "Top 9",
            "Top 8",
            "Top 7",
            "Top 6",
            "Top 5",
            "Top 4",
            "Top 3",
            "Top 2",
            "Top Ten",
            "Top Nine",
            "Top Eight",
            "Top Seven",
            "Top Six",
            "Top Five",
            "Top Four",
            "Top Three",
            "Top Two",
        ]
    ),
}


def tube_watch():
    args = parse_args("tube.db", default_chromecast="Living Room TV")
    args.action = Subcommand.tubewatch

    process_actions(args)


def tube_listen():
    args = parse_args("tube.db", default_chromecast="Xylo and Orchestra")
    args.action = Subcommand.tubelisten

    try:
        process_actions(args)
    finally:
        if args.chromecast:
            Path(CAST_NOW_PLAYING).unlink(missing_ok=True)
