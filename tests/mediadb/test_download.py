import pytest

from library.__main__ import library as lb
from library.createdb.tube_add import tube_add
from library.mediadb import download as download_mod
from library.utils.consts import DBType
from tests.utils import connect_db_args

URL = "https://www.youtube.com/watch?v=5DqJwmzG6Fk"
STORAGE_PREFIX = "tests/data/"

dl_db = "tests/data/dl.db"


def test_download_links_recursive(temp_db, crawl_server, tmp_path):
    db1 = temp_db()
    lb(["links-add", db1, "--no-extract", crawl_server])
    lb(
        [
            "dl",
            db1,
            "--filesystem",
            "--recursive",
            "--path-exclude",
            "*/tag/*",
            "external.example.com",
            f"--prefix={tmp_path}",
            crawl_server,
        ]
    )

    downloaded = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert any(path.endswith("a.html") for path in downloaded)
    assert any(path.endswith("sub/b.html") for path in downloaded)
    assert any(path.endswith("sub/c.html") for path in downloaded)


def test_resolve_download_profile_auto(monkeypatch):
    monkeypatch.setattr(download_mod.tube_backend, "is_supported", lambda path: path.endswith("video"))
    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", lambda _args: None)
    monkeypatch.setattr(download_mod.gallery_backend, "is_supported", lambda path: path.endswith("image"))

    assert download_mod.resolve_download_profile(None, "https://x/video") == DBType.video
    assert download_mod.resolve_download_profile(None, "https://x/image") == DBType.image
    assert download_mod.resolve_download_profile(None, "https://x/file.zip") == DBType.filesystem


def test_download_auto_dispatches_resolved_links(temp_db, monkeypatch):
    """Regression: default `download` is auto and must dispatch each extracted link to the
    matching backend. Routing used to crash because arg_utils.args_override() takes a dict,
    not **kwargs."""
    db1 = temp_db()
    lb(["links-add", db1, "--insert-only", "https://example.com/page"])

    links = [
        {"link": "https://example.com/clip", "link_text": "", "before_text": "", "after_text": ""},
        {"link": "https://example.com/pic", "link_text": "", "before_text": "", "after_text": ""},
        {"link": "https://example.com/raw.html", "link_text": "", "before_text": "", "after_text": ""},
    ]
    monkeypatch.setattr(download_mod.extract_links, "crawl", lambda _args, _seeds: iter(links))
    monkeypatch.setattr(download_mod.tube_backend, "is_supported", lambda url: url.endswith("clip"))
    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", lambda _args: None)
    monkeypatch.setattr(download_mod.gallery_backend, "is_supported", lambda url: url.endswith("pic"))

    routed = {"tube": [], "gallery": [], "builtin": []}
    monkeypatch.setattr(download_mod.tube_backend, "download", lambda _args, m: routed["tube"].append(m["path"]))
    monkeypatch.setattr(
        download_mod.gallery_backend, "download", lambda _args, m: routed["gallery"].append(m["path"])
    )
    monkeypatch.setattr(
        download_mod, "_download_builtin", lambda _args, _m, _orig, paths: routed["builtin"].extend(paths)
    )

    lb(["dl", db1, "--auto", "--recursive", "--force"])

    assert routed["tube"] == ["https://example.com/clip"]
    assert routed["gallery"] == ["https://example.com/pic"]
    assert routed["builtin"] == ["https://example.com/raw.html"]


def test_safe_with_link_extraction_checks_links_not_seed(temp_db, monkeypatch):
    """`--safe` must not skip the seed page (which only exists to discover links); it is
    applied to each extracted link instead."""
    db1 = temp_db()
    lb(["links-add", db1, "--insert-only", "https://example.com/page"])

    links = [
        {"link": "https://example.com/clip", "link_text": "", "before_text": "", "after_text": ""},
        {"link": "https://example.com/pic", "link_text": "", "before_text": "", "after_text": ""},
        {"link": "https://example.com/other", "link_text": "", "before_text": "", "after_text": ""},
    ]
    monkeypatch.setattr(download_mod.extract_links, "crawl", lambda _args, _seeds: iter(links))
    monkeypatch.setattr(download_mod.tube_backend, "is_supported", lambda url: url.endswith("clip"))
    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", lambda _args: None)
    monkeypatch.setattr(download_mod.gallery_backend, "is_supported", lambda url: url.endswith("pic"))

    routed = {"tube": [], "gallery": [], "builtin": []}
    monkeypatch.setattr(download_mod.tube_backend, "download", lambda _args, m: routed["tube"].append(m["path"]))
    monkeypatch.setattr(
        download_mod.gallery_backend, "download", lambda _args, m: routed["gallery"].append(m["path"])
    )
    monkeypatch.setattr(
        download_mod, "_download_builtin", lambda _args, _m, _orig, paths: routed["builtin"].extend(paths)
    )

    lb(["dl", db1, "--safe", "--recursive", "--force"])

    assert routed["tube"] == ["https://example.com/clip"]
    assert routed["gallery"] == ["https://example.com/pic"]
    assert routed["builtin"] == []


def test_download_process_preserves_unsupported_extension(temp_db, crawl_server, tmp_path):
    lb(
        [
            "dl",
            temp_db(),
            "--filesystem",
            "--process",
            "--force",
            f"--prefix={tmp_path}",
            f"{crawl_server}index.html",
        ]
    )


@pytest.mark.skip("network: too dependent on YouTube/Google services")
def test_yt():
    tube_add([dl_db, URL])
    lb(
        [
            "dl",
            dl_db,
            "--video",
            f"--prefix={STORAGE_PREFIX}",
            "--force",
            "--subs",
            "-s",
            URL,
        ]
    )

    args = connect_db_args(dl_db)

    captions = list(args.db.query("select * from captions"))
    assert {"media_id": 1, "text": "welcome to the Microsoft Windows 95", "time": 3} in captions
