from tests.utils import tube_db
from xklb.lb import library as lb


def test_playlists(capsys):
    lb(["playlists", tube_db])
    captured = capsys.readouterr().out
    assert "duration" in captured

    lb(["playlists", tube_db, "test playlist"])
    captured = capsys.readouterr().out
    assert "test playlist" in captured

    lb(["playlists", tube_db, "-pa"])
    captured = capsys.readouterr().out
    assert "Aggregate of playlists" in captured
    assert "playlists_count" in captured
    assert "media_count" in captured
