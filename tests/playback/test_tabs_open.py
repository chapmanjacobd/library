from unittest import mock

import pandas, pytest  # noqa: pandas needs to be imported before freezegun because 'FakeDatetime' is dynamically allocated
from freezegun import freeze_time

from tests.utils import connect_db_args
from library.__main__ import library as lb
from library.mediadb import db_history
from library.playback import tabs_open
from library.utils import consts

TEST_URL = "https://unli.xyz/proliferation/verbs.html"


def test_frequency_filter():
    daily_row = {"path": TEST_URL, "frequency": "daily", "time_valid": 86101}
    weekly_row = {"path": TEST_URL, "frequency": "weekly", "time_valid": 86101}
    monthly_row = {"path": TEST_URL, "frequency": "monthly", "time_valid": 86101}

    assert tabs_open.frequency_filter([], [daily_row]) == []
    assert tabs_open.frequency_filter([("monthly", 1)], [daily_row]) == []
    assert tabs_open.frequency_filter([("daily", 1)], [daily_row]) == [daily_row]
    assert tabs_open.frequency_filter([("monthly", 1), ("daily", 1)], [monthly_row, weekly_row, daily_row]) == [
        monthly_row,
        daily_row,
    ]
    assert tabs_open.frequency_filter([("daily", 50)], [daily_row] * 50) == [daily_row] * 50
    assert tabs_open.frequency_filter([("weekly", 50)], [weekly_row] * 50) == [weekly_row] * 8
    assert tabs_open.frequency_filter([("monthly", 250)], [monthly_row] * 10) == [monthly_row] * 9
    assert tabs_open.frequency_filter([("monthly", 250)], [monthly_row] * 9) == [monthly_row] * 9
    assert tabs_open.frequency_filter([("monthly", 250)], [monthly_row] * 8) == [monthly_row] * 8


@mock.patch("library.playback.tabs_open.play")
def test_simple(play_mocked, temp_db):
    db1 = temp_db()
    with freeze_time("1970-01-01 00:00:01") as clock:
        lb(["tabsadd", db1, "--frequency", "weekly", TEST_URL])

        clock.move_to("1970-01-01 00:10:00")
        with pytest.raises(SystemExit):
            lb(["tabs", db1])

        clock.move_to("1970-01-08 00:00:00")
        lb(["tabs", db1])
        out = play_mocked.call_args[0][1][0]
        assert out["time_valid"] > 100000

        args = connect_db_args(db1)
        db_history.add(args, [TEST_URL], time_played=consts.today_stamp(), mark_done=True)
        with pytest.raises(SystemExit):  # it should not be available until the week after
            lb(["tabs", db1])

        clock.move_to("1970-01-15 00:00:00")
        lb(["tabs", db1])
        out = play_mocked.call_args[0][1][0]
        assert out["time_valid"] == 1209300


@mock.patch("library.playback.tabs_open.play")
def test_immediate(play_mocked, temp_db):
    db1 = temp_db()
    with freeze_time("1970-02-01 00:00:00") as clock:
        lb(["tabsadd", db1, "--allow-immediate", TEST_URL])

        lb(["tabs", db1])
        out = play_mocked.call_args[0][1][0]
        assert out == {
            "path": TEST_URL,
            "frequency": "monthly",
            "time_valid": 2678100,
        }

        args = connect_db_args(db1)
        db_history.add(args, [TEST_URL], time_played=consts.today_stamp(), mark_done=True)
        with pytest.raises(SystemExit):  # it should not be available until the month after
            lb(["tabs", db1])

        clock.move_to("1970-03-01 00:00:00")
        lb(["tabs", db1])
        out = play_mocked.call_args[0][1][0]
        assert out == {
            "path": TEST_URL,
            "frequency": "monthly",
            "time_valid": 5097300,
        }
