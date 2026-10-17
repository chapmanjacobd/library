from types import SimpleNamespace

from library.misc.export_text import media_to_files


class FakeDB:
    def query(self, _query):
        return [{"path": "/media/song.mp3", "title": "Song", "artist": "Artist"}]


def test_media_to_files_writes_html_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    media_to_files(SimpleNamespace(db=FakeDB()))

    output = (tmp_path / "Song.html").read_text()
    assert "/media/song.mp3" in output
    assert "artist: Artist" in output
