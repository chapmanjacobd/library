import shlex
from argparse import ArgumentParser
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tests.utils import v_db
from xklb.lb import library as lb
from xklb.utils import arggroups

fs_flags = [
    ("--modified-within '1 second'", 0, ""),
    ("--deleted-within '1 day'", 0, ""),
    ("--downloaded-before '1 day'", 0, ""),
    ("--limit 1", 1, "corrupt.mp4"),
    ("-L 1", 1, "corrupt.mp4"),
    ("--online-media-only", 1, "https://test"),
    ("--offset 1", 4, "test.mp4"),
    ("-s tests -s 'tests AND data' -E 2 -s test -E 3", 4, "corrupt.mp4"),
    ("--created-within '30 years'", 5, "corrupt.mp4"),
    ("--created-before '1 second'", 5, "corrupt.mp4"),
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
    ("--deleted-before '1 day'", 5, "corrupt.mp4"),
]


media_flags = [
    ("--no-video", 0, ""),
    ("-B --solo", 0, ""),
    ("-P s", 0, ""),  # test_media_player must run first  # TODO: move to new function to test before / after
    ("-w 'play_count=0'", 0, ""),
    # ("-P f", 5, "test"),  # TODO: make a specific test for this that doesn't have a race condition
    # ("-P fo", 5, "test.mp4"),
    # ("-P n", 5, "test.mp4"),
    ("--partial o", 5, "corrupt.mp4"),
    ("-P p", 5, "corrupt.mp4"),
    ("-P pt", 5, "corrupt.mp4"),
    ("-P t", 5, "corrupt.mp4"),
    ("-w 'play_count>0'", 5, "corrupt.mp4"),
    ("-w 'time_played>0'", 5, "corrupt.mp4"),
    ("-w 'done>0'", 5, "corrupt.mp4"),
    ("--played-within '3 days'", 5, "corrupt.mp4"),
    ("--played-before '10 years'", 0, ""),
    ("--no-subtitles", 1, "test_frame.gif"),
    ("-w subtitle_count=1", 1, "corrupt.mp4"),
    ("--fetch-siblings each", 1, "corrupt.mp4"),
    ("--no-audio", 2, "test.gif"),
    ("-w audio_count=1", 2, "corrupt.mp4"),
    ("-d+0 -d-10", 3, "corrupt.mp4"),
    ("-d=-1", 3, "corrupt.mp4"),
    ("--subtitles", 3, "corrupt.mp4"),
    ("--duration-from-size=-100Mb", 3, "corrupt.mp4"),
    ("--fetch-siblings all", 4, "corrupt.mp4"),
    ("-B --folders-counts=-4", 4, "corrupt.mp4"),
    ("-B --folder-counts=-16", 4, "corrupt.mp4"),
    ("-B --folder-sizes=-5MB", 4, "corrupt.mp4"),
    ("-B --sibling", 4, "corrupt.mp4"),
    ("-R", 4, "corrupt.mp4"),
    ("-RCO", 4, "test.gif"),
    ("-RR", 4, "corrupt.mp4"),
    ("-B --sort-groups-by size", 4, "corrupt.mp4"),
    ("-B --parents", 4, "corrupt.mp4"),
    ("-u duration", 5, "corrupt.mp4"),
    ("--portrait", 5, "corrupt.mp4"),
    ("--fetch-siblings if-audiobook", 5, "corrupt.mp4"),
    ("-C --n-clusters 3 --stop-words xklb", 5, "test.gif"),
    ("-C --near-duplicates", 5, "corrupt.mp4"),
    ("-O duration", 5, "test.gif"),
    ("-O locale_duration", 5, "test.gif"),
    ("-O locale_size", 5, "test_frame.gif"),
    ("-O reverse_path_path", 5, "https://test"),
    ("-O size", 5, "test_frame.gif"),
    ("-O", 5, "corrupt.mp4"),
    ("-w 'playhead is NULL'", 5, "corrupt.mp4"),
    ("-w time_deleted=0", 5, "corrupt.mp4"),
]

temp_parser = ArgumentParser(add_help=False)
arggroups.sql_fs(temp_parser)
opts = temp_parser._actions


@pytest.mark.parametrize("o", opts)
def test_flags_covered(o):
    assert any(s in xs for s in o.option_strings for xs in [t[0] for t in fs_flags] + [t[0] for t in media_flags]), (
        "Option %s is not covered" % o.option_strings
    )


@mock.patch("xklb.playback.media_player.play_list", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize("flags,count,first", fs_flags)
def test_fs_flags(play_mocked, flags, count, first):
    for subcommand in ["fs", "media"]:
        if count == 0:
            with pytest.raises(SystemExit):
                lb([subcommand, v_db, *shlex.split(flags)])
        else:
            lb([subcommand, v_db, *shlex.split(flags)])
            out = play_mocked.call_args[0][1]

            assert len(out) == count
            if first:
                p = out[0]["path"]
                p = p if first.startswith("http") else Path(p).name
                assert p == first, "%s does not match %s" % (p, first)


@mock.patch("xklb.playback.media_player.play_list", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize("flags,count,first", media_flags)
def test_media_flags(play_mocked, flags, count, first):
    for subcommand in ["media", "wt"]:
        if count == 0:
            with pytest.raises(SystemExit):
                lb([subcommand, v_db, *shlex.split(flags)])
        else:
            lb([subcommand, v_db, *shlex.split(flags)])
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


@mock.patch("xklb.playback.media_printer.media_printer", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize("flags", printing_flags)
def test_print_flags(print_mocked, flags):
    for subcommand in ["fs", "media"]:
        lb([subcommand, v_db, *shlex.split(flags)])
        out = print_mocked.call_args[0][1]
        assert out is not None, f"Test failed for {flags}"
