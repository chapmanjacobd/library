import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from library.__main__ import library as lb
from tests.utils import p

history_db = p("tests/data/history.db")
lb(["fs-add", history_db, "--scan-subtitles", p("tests/data/"), "-E", "Youtube"])
lb(["history-add", history_db, p("tests/data/corrupt.mp4")])

history_flags = [
    ("--played-before '10 years'", 0, ""),
    ("-P s", 3, ""),
    ("-w 'play_count=0'", 3, ""),
    ("-P f", 1, "corrupt.mp4"),
    ("-P fo", 1, "corrupt.mp4"),
    ("-P n", 1, "corrupt.mp4"),
    ("--partial o", 1, "corrupt.mp4"),
    ("-P p", 1, "corrupt.mp4"),
    ("-P pt", 1, "corrupt.mp4"),
    ("-P t", 1, "corrupt.mp4"),
    ("-w 'playhead=0'", 1, "corrupt.mp4"),
    ("-w 'play_count>0'", 1, "corrupt.mp4"),
    ("-w 'time_played>0'", 1, "corrupt.mp4"),
    ("-w 'done>0'", 1, "corrupt.mp4"),
    ("--played-within '3 days'", 1, "corrupt.mp4"),
]


@mock.patch("library.playback.media_player.play_list", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize(("flags", "count", "first"), history_flags)
def test_history_flags(play_mocked, flags, count, first):
    if count == 0:
        with pytest.raises(SystemExit):
            lb(["media", history_db, *shlex.split(flags)])
    else:
        lb(["media", history_db, *shlex.split(flags), "-u", "path"])
        out = play_mocked.call_args[0][1]

        assert len(out) == count
        if first:
            p = out[0]["path"]
            p = p if first.startswith("http") else Path(p).name
            assert p == first, "%s does not match %s" % (p, first)
