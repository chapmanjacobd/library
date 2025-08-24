import shlex
from argparse import ArgumentParser
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from library.__main__ import library as lb
from library.mediadb import db_history
from library.utils import arggroups
from tests.playback.test_play_history import history_flags
from tests.utils import connect_db_args, v_db

fs_flags = [
    ("--modified-within '1 second'", 0, ""),
    ("--time-modified '-1 second'", 0, ""),
    ("--deleted-within '1 day'", 0, ""),
    ("--deleted", 0, ""),
    ("--downloaded-before '1 day'", 0, ""),
    ("--limit 1", 1, "corrupt.mp4"),
    ("-L 1", 1, "corrupt.mp4"),
    ("--online-media-only", 1, "https://test/?tags%5B%5D="),
    ("--no-fts -s https://test/?tags%5B%5D=", 1, "https://test/?tags%5B%5D="),
    ("--no-fts -s https://test/?tags[]=", 1, "https://test/?tags%5B%5D="),
    ("--no-url-encode-search --no-fts -s https://test/?tags%5B%5D=", 1, "https://test/?tags%5B%5D="),
    ("--no-url-encode-search --no-fts -s https://test/?tags[]=", 0, ""),
    ("--offset 1", 4, "test.mp4"),
    ("-s tests -s 'tests AND data' -E 2 -s test -E 3", 4, "corrupt.mp4"),
    ("--created-within '30 years'", 5, "corrupt.mp4"),
    ("--created-before '1 second'", 5, "corrupt.mp4"),
    ("--time-created '-30 years'", 5, "corrupt.mp4"),
    ("--time-created '+1 second'", 5, "corrupt.mp4"),
    ("--downloaded-within '1 day'", 4, "corrupt.mp4"),
    ("--playlists tests/data/", 4, ""),
    ("--local-media-only", 4, "corrupt.mp4"),
    ("-S+0 -S-10", 4, "corrupt.mp4"),
    ("-S=-1Mi", 4, "corrupt.mp4"),
    ("-w 'size/size<50000'", 4, "corrupt.mp4"),
    ("--random", 5, ""),
    ("-u random", 5, ""),
    ("-u size", 5, "corrupt.mp4"),
    ("-s test", 5, "corrupt.mp4"),
    ("test --exact", 5, "corrupt.mp4"),
    ("test --flex", 5, "corrupt.mp4"),
    ("test --no-fts", 5, "corrupt.mp4"),
    ("--modified-before '1 second'", 5, "corrupt.mp4"),
    ("--time-modified '+1 second'", 5, "corrupt.mp4"),
    ("--deleted-before '1 day'", 5, "corrupt.mp4"),
    ("--hide-deleted", 5, "corrupt.mp4"),
    ("--no-hide-deleted", 5, "corrupt.mp4"),
]

media_flags = [
    ("--no-video", 0, ""),
    ("-B --solo", 0, ""),
    ("-B --episode", 0, ""),
    ("--no-subtitles", 1, "test_frame.gif"),
    ("-w subtitle_count=1", 1, "corrupt.mp4"),
    ("--fetch-siblings=4", 4, "corrupt.mp4"),
    ("--fetch-siblings each", 4, "corrupt.mp4"),
    ("--fetch-siblings each --fetch-siblings-max=1", 1, "corrupt.mp4"),
    ("--no-audio", 2, "test.gif"),
    ("-w audio_count=1", 2, "corrupt.mp4"),
    ("-d+0 -d-10", 3, "corrupt.mp4"),
    ("-d=-1", 3, "corrupt.mp4"),
    ("--subtitles", 3, "corrupt.mp4"),
    ("--duration-from-size=-100Mb", 3, "corrupt.mp4"),
    ("--fetch-siblings all", 4, "corrupt.mp4"),
    ("-B --folder-counts=-4", 4, "corrupt.mp4"),
    ("-B --file-counts=-16", 4, "corrupt.mp4"),
    ("-B --folder-sizes=-5MB", 4, "corrupt.mp4"),
    ("-R", 4, "corrupt.mp4"),
    ("-RC", 4, "test.gif"),
    ("-RR", 4, "corrupt.mp4"),
    ("-B --sort-groups-by size", 4, "corrupt.mp4"),
    ("-B --parents", 4, "corrupt.mp4"),
    ("-u duration", 5, "corrupt.mp4"),
    ("--portrait", 5, "corrupt.mp4"),
    ("--fetch-siblings if-audiobook", 5, "corrupt.mp4"),
    ("-C --n-clusters 3 --stop-words library", 5, "test.gif"),
    ("-C --duplicates", 5, "corrupt.mp4"),
    ("-O duration", 5, "test.gif"),
    ("-O locale_duration", 5, "test.gif"),
    ("-O locale_size", 5, "test_frame.gif"),
    ("-O reverse_path_path", 5, "https://test/?tags%5B%5D="),
    ("-O size", 5, "test_frame.gif"),
    ("-w time_deleted=0", 5, "corrupt.mp4"),
]

args = connect_db_args(v_db)
db_history.create(args)


temp_parser = ArgumentParser(add_help=False)
arggroups.sql_fs(temp_parser)
opts = temp_parser._actions


@pytest.mark.parametrize("o", opts)
def test_flags_covered(o):
    assert any(
        s in xs
        for s in o.option_strings
        for xs in [t[0] for t in fs_flags] + [t[0] for t in media_flags] + [t[0] for t in history_flags]
    ), ("Option %s is not covered" % o.option_strings)


@mock.patch("library.playback.media_player.play_list", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize(("flags", "count", "first"), fs_flags)
def test_fs_flags(play_mocked, flags, count, first):
    for subcommand in ["media"]:
        if count == 0:
            with pytest.raises(SystemExit):
                lb([subcommand, v_db, *shlex.split(flags)])
        else:
            lb([subcommand, v_db, *shlex.split(flags), "-u", "path"])
            out = play_mocked.call_args[0][1]

            assert len(out) == count
            if first:
                p = out[0]["path"]
                p = p if first.startswith("http") else Path(p).name
                assert p == first, "%s does not match %s" % (p, first)


@mock.patch("library.playback.media_player.play_list", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize(("flags", "count", "first"), media_flags)
def test_media_flags(play_mocked, flags, count, first):
    for subcommand in ["media", "wt"]:
        if count == 0:
            with pytest.raises(SystemExit):
                lb([subcommand, v_db, *shlex.split(flags)])
        else:
            lb([subcommand, v_db, *shlex.split(flags), "-u", "path"])
            out = play_mocked.call_args[0][1]

            assert len(out) == count
            if first:
                p = out[0]["path"]
                p = p if first.startswith("http") else Path(p).name
                assert p == first, "%s does not match %s" % (p, first)


printing_flags = [
    "-p",
    "-B -pa",
    "-pa",
    "-pb",
    "-pf",
    "-p df",
    "-p bf",
    "-p --cols '*' -L inf",
]


@mock.patch("library.playback.media_printer.media_printer", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize("flags", printing_flags)
def test_print_flags(print_mocked, flags):
    for subcommand in ["media"]:
        lb([subcommand, v_db, *shlex.split(flags)])
        out = print_mocked.call_args[0][1]
        assert out is not None, f"Test failed for {flags}"
