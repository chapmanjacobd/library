import pytest

from types import SimpleNamespace

from library.__main__ import library as lb
from library.database.add.tube_add import tube_add
from library.database.manage import db_media
from library.download import download as download_mod
from library.utils import sqlgroups
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
            "links",
            "download",
            "--db",
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


def test_download_add_without_db_is_noop():
    """DB-less commands (eg. `library links download`) download without recording; download_add
    must tolerate a missing database."""
    db_media.download_add(SimpleNamespace(), "https://example.com/x")  # must not raise


def test_resolve_download_profile_auto(monkeypatch):
    monkeypatch.setattr(download_mod.tube_backend, "is_supported", lambda path: path.endswith("video"))
    monkeypatch.setattr(download_mod.gallery_backend, "gallery_dl_available", lambda: True)
    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", lambda _args: None)
    monkeypatch.setattr(download_mod.gallery_backend, "is_supported", lambda path: path.endswith("image"))

    assert download_mod.resolve_download_profile(None, "https://x/video") == DBType.video
    assert download_mod.resolve_download_profile(None, "https://x/image") == DBType.image
    assert download_mod.resolve_download_profile(None, "https://x/file.zip") == DBType.filesystem


def test_resolve_download_profile_auto_without_gallery_dl(monkeypatch):
    """gallery-dl is an optional (deluxe) dependency; `auto` must fall back to yt-dlp and
    the built-in downloader rather than crashing when it is missing."""
    monkeypatch.setattr(download_mod.tube_backend, "is_supported", lambda path: path.endswith("video"))
    monkeypatch.setattr(download_mod.gallery_backend, "gallery_dl_available", lambda: False)

    def boom(*_args, **_kwargs):
        raise AssertionError("gallery-dl must not be loaded when it is unavailable")

    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", boom)

    assert download_mod.resolve_download_profile(None, "https://x/video") == DBType.video
    assert download_mod.resolve_download_profile(None, "https://x/image") == DBType.filesystem


def test_route_links_direct_batches_builtin_paths(monkeypatch):
    routed = []
    args = SimpleNamespace(direct=True, profile=DBType.auto)

    monkeypatch.setattr(
        download_mod.tube_backend,
        "download",
        lambda *_args: pytest.fail("direct downloads must not use yt-dlp"),
    )
    monkeypatch.setattr(
        download_mod.gallery_backend,
        "download",
        lambda *_args: pytest.fail("direct downloads must not use gallery-dl"),
    )

    download_mod.route_links(
        args,
        {"path": "https://example.com/page"},
        "https://example.com/page",
        ["https://example.com/a", "https://example.com/b"],
        {},
        lambda _args, _media, original, paths: routed.append((original, paths)),
    )

    assert routed == [
        ("https://example.com/page", ["https://example.com/a", "https://example.com/b"]),
    ]


@pytest.mark.parametrize(("backend_result", "finalized"), [(True, True), (False, False)])
def test_route_links_finalizes_source_only_after_backend_success(monkeypatch, backend_result, finalized):
    finalized_paths = []
    args = SimpleNamespace(direct=False, profile=DBType.video)
    monkeypatch.setattr(download_mod.tube_backend, "download", lambda *_args: backend_result)
    monkeypatch.setattr(download_mod, "_finalize_source", lambda _args, path: finalized_paths.append(path))

    download_mod.route_links(
        args,
        {"path": "https://example.com/page"},
        "https://example.com/page",
        ["https://example.com/video"],
        {},
        lambda *_args: pytest.fail("video downloads must not use the built-in downloader"),
    )

    assert finalized_paths == (["https://example.com/page"] if finalized else [])


def test_route_links_finalizes_source_when_safe_filters_every_link(monkeypatch):
    finalized_paths = []
    args = SimpleNamespace(direct=False, profile=DBType.video)
    monkeypatch.setattr(download_mod, "safe_supported", lambda *_args: False)
    monkeypatch.setattr(
        download_mod.tube_backend,
        "download",
        lambda *_args: pytest.fail("filtered links must not reach the backend"),
    )
    monkeypatch.setattr(download_mod, "_finalize_source", lambda _args, path: finalized_paths.append(path))

    download_mod.route_links(
        args,
        {"path": "https://example.com/page"},
        "https://example.com/page",
        ["https://example.com/unsupported"],
        {},
        lambda *_args: pytest.fail("filtered links must not reach the built-in downloader"),
        safe_links=True,
    )

    assert finalized_paths == ["https://example.com/page"]


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
    monkeypatch.setattr(download_mod.gallery_backend, "gallery_dl_available", lambda: True)
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

    lb(["links", "download", "--db", db1, "--auto", "--recursive", "--force"])

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
    monkeypatch.setattr(download_mod.gallery_backend, "gallery_dl_available", lambda: True)
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

    lb(["links", "download", "--db", db1, "--safe", "--recursive", "--force"])

    assert routed["tube"] == ["https://example.com/clip"]
    assert routed["gallery"] == ["https://example.com/pic"]
    assert routed["builtin"] == []


def test_safe_image_excludes_direct_links(temp_db, monkeypatch):
    """An explicit `--image --safe` run only accepts real gallery-dl site extractors;
    direct/generic (catch-all) links are skipped, exactly like `auto`."""
    db1 = temp_db()
    lb(["links-add", db1, "--insert-only", "https://example.com/album"])
    lb(["links-add", db1, "--insert-only", "https://example.com/pic.png"])

    monkeypatch.setattr(download_mod.gallery_backend, "gallery_dl_available", lambda: True)
    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", lambda _args: None)
    monkeypatch.setattr(download_mod.gallery_backend, "is_supported", lambda url: url.endswith("/album"))

    routed = {"gallery": []}
    monkeypatch.setattr(
        download_mod.gallery_backend, "download", lambda _args, m: routed["gallery"].append(m["path"])
    )

    lb(["download", "--db", db1, "--image", "--safe", "--force"])

    assert routed["gallery"] == ["https://example.com/album"]


def test_safe_without_link_extraction_filters_rows(temp_db, monkeypatch):
    """`--safe` without link extraction skips unsupported rows (the loop re-check covers
    rows that did not come from the SQL query)."""
    db1 = temp_db()
    lb(["links-add", db1, "--insert-only", "https://example.com/clip"])
    lb(["links-add", db1, "--insert-only", "https://example.com/other"])

    monkeypatch.setattr(download_mod.tube_backend, "is_supported", lambda url: url.endswith("clip"))
    monkeypatch.setattr(download_mod.gallery_backend, "gallery_dl_available", lambda: True)
    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", lambda _args: None)
    monkeypatch.setattr(download_mod.gallery_backend, "is_supported", lambda _url: False)

    routed = {"tube": [], "builtin": []}
    monkeypatch.setattr(download_mod.tube_backend, "download", lambda _args, m: routed["tube"].append(m["path"]))
    monkeypatch.setattr(
        download_mod, "_download_builtin", lambda _args, _m, _orig, paths: routed["builtin"].extend(paths)
    )

    lb(["download", "--db", db1, "--safe", "--force"])

    assert routed["tube"] == ["https://example.com/clip"]
    assert routed["builtin"] == []


def test_safe_filter_is_pushed_into_sql(temp_db, monkeypatch):
    """`--safe` (without link extraction) is also applied in SQL so `--limit` backfills
    supported URLs; the loop re-checks rows that did not come from the query."""
    db1 = temp_db()
    lb(["links-add", db1, "--insert-only", "https://example.com/clip"])

    monkeypatch.setattr("sys.argv", ["download", "--db", db1, "--safe", "--print"])
    args = download_mod.parse_args()

    query, _ = sqlgroups.construct_download_query(args)

    assert "is_supported(m.path)" in query


def test_download_process_preserves_unsupported_extension(crawl_server, tmp_path):
    lb(
        [
            "download",
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
            "download",
            "--db",
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
