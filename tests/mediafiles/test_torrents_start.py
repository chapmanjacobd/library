import sys
from types import ModuleType, SimpleNamespace

from library.mediafiles import torrents_start


def test_start_qbittorrent_allows_unauthenticated_api(monkeypatch):
    class LoginFailedError(Exception):
        pass

    class Client:
        def __init__(self, **_kwargs):
            pass

        def auth_log_in(self):
            raise LoginFailedError

    qbittorrentapi = ModuleType("qbittorrentapi")
    qbittorrentapi.Client = Client
    qbittorrentapi.LoginFailed = LoginFailedError
    qbittorrentapi.APIConnectionError = RuntimeError
    monkeypatch.setitem(sys.modules, "qbittorrentapi", qbittorrentapi)
    monkeypatch.setattr(
        torrents_start.shutil,
        "which",
        lambda _command: (_ for _ in ()).throw(AssertionError("qBittorrent should not be restarted")),
    )

    args = SimpleNamespace(host="localhost", port=8080, username=None, password=None)

    assert isinstance(torrents_start.start_qBittorrent(args), Client)
