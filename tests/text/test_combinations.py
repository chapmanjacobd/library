import pytest

from xklb.lb import library as lb


def test_lb(capsys):
    lb(["combinations", "--prop1", "opt1", "--prop1", "opt2", "--prop2", "A", "--prop2", "B"])
    captured = capsys.readouterr().out
    assert (
        captured
        == """{"prop1": "opt1", "prop2": "A"}
{"prop1": "opt1", "prop2": "B"}
{"prop1": "opt2", "prop2": "A"}
{"prop1": "opt2", "prop2": "B"}
"""
    )


def test_lb_missing_arguments(temp_db):
    db1 = temp_db()
    with pytest.raises(SystemExit):
        lb(["combinations", db1])
