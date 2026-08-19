import sys
from types import ModuleType, SimpleNamespace

import pytest

from library.__main__ import library as lb
from library.playback import surf


def test_streaming_tab_loader_stops_at_stdin_eof(monkeypatch, mock_stdin):
    opened = []
    monkeypatch.setattr(surf, "parse_args", lambda: SimpleNamespace(target_hosts=None, count=2))
    monkeypatch.setattr(surf, "open_tabs", lambda _args, urls: opened.extend(urls))

    api_module = ModuleType("brotab.api")
    api_module.SingleMediatorAPI = lambda _clients: SimpleNamespace(list_tabs=lambda _args: [])
    main_module = ModuleType("brotab.main")
    main_module.create_clients = lambda _target_hosts: []
    monkeypatch.setitem(sys.modules, "brotab", ModuleType("brotab"))
    monkeypatch.setitem(sys.modules, "brotab.api", api_module)
    monkeypatch.setitem(sys.modules, "brotab.main", main_module)

    with mock_stdin("https://example.com\n"):
        surf.streaming_tab_loader()

    assert opened == ["https://example.com"]


def test_surf_rejects_database_option(capsys):
    with pytest.raises(SystemExit):
        lb(["surf", "--database", "library.db"])

    assert "unrecognized arguments" in capsys.readouterr().err
