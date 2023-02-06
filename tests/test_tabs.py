import unittest
from unittest import mock

from xklb.lb import library as lb
from xklb.tabs_extract import tabs_add

tabs_db = ["tests/data/tabs.db"]
tabs_add([*tabs_db, "https://unli.xyz/proliferation/verbs.html"])


class TestTabs(unittest.TestCase):
    @mock.patch("xklb.tabs_actions.play")
    def test_lb_tabs(self, play_mocked):
        lb(["tabs", *tabs_db])
        out = play_mocked.call_args[0][1]
        assert out == {
            "path": "https://unli.xyz/proliferation/verbs.html",
            "frequency": "monthly",
            "time_valid": 2678400,
        }
