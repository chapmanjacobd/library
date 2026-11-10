from library.__main__ import library as lb
from library.captions.search import merge_captions
from tests.utils import v_db


def test_merge_captions_ignores_missing_text():
    captions = [
        {"path": "missing.srt", "time": 0, "text": None},
        {"path": "valid.srt", "time": 0, "text": "valid caption"},
    ]

    assert merge_captions(type("Args", (), {"overlap": 8})(), captions) == [
        {
            "path": "valid.srt",
            "time": 0,
            "text": "valid caption",
            "end": len("valid caption") / 4.2 / 220 * 60,
        }
    ]


def test_search(capsys):
    lb(["captions", v_db])
    captured = capsys.readouterr().out
    assert "end" in captured.replace("\n", "")
    assert len(captured) > 150
