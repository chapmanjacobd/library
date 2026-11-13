import tempfile
from types import SimpleNamespace

import pytest

from library.__main__ import library as lb
from library.links import extract_links
from library.utils import arggroups, web
from library.utils.consts import DBType


def _filter_args(**overrides):
    args = SimpleNamespace(
        href=False,
        url=False,
        src=False,
        data_src=False,
        srcset=False,
        data_srcset=False,
        case_sensitive=False,
        path_include=[],
        path_exclude=[],
        text_include=[],
        text_exclude=[],
        before_include=[],
        before_exclude=[],
        after_include=[],
        after_exclude=[],
        url_encode_filters=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_filter_links_does_not_url_encode_by_default():
    args = _filter_args(path_include=["action=download"], path_exclude=["&id="])

    arggroups.filter_links_post(args)

    assert args.path_include == ["action=download"]
    assert args.path_exclude == ["&id="]


def test_filter_links_url_encode_filters():
    args = _filter_args(path_include=["action=download"], path_exclude=["&id="], url_encode_filters=True)

    arggroups.filter_links_post(args)

    assert args.path_include == ["action%3Ddownload"]
    assert args.path_exclude == ["%26id%3D"]


def test_extract_links_path_include_with_query_string(tmp_path, capsys):
    html = tmp_path / "index.html"
    html.write_text('<a href="https://www.example.com/test.php?action=download&id=20">download</a>')

    lb(["extract-links", "--local-html", str(html), "--path-include", "action=download"])

    assert capsys.readouterr().out.split() == ["https://www.example.com/test.php?action=download&id=20"]


def test_links_local_html_none(capsys):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp_html:
        temp_html.write(b"<html><head><title>Real Title</title></head><body>Content</body></html>")
        temp_html.flush()

        lb(["extract-links", "--local-html", temp_html.name])

    captured = capsys.readouterr().out.replace("\n", "")
    assert captured == ""


def test_links_local_html(capsys):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp_html:
        temp_html.write(
            b"""<meta http-equiv="content-type" content="text/html; charset=utf-8"><li>s, flour, and salt.</li>
<li><i><a href="https://en.wikipedia.org/w/index.php?title=Tortang_kamote&amp;action=edit&amp;redlink=1" class="new" title="Tortang kamote (page does not exist)">Tortang kamote</a></i> - an omelette made with mashed sweet potato, eggs, flour, and salt.</li>"""
        )
        temp_html.flush()

        lb(["extract-links", "--local-html", temp_html.name])

    captured = capsys.readouterr().out.replace("\n", "")
    assert captured == "https://en.wikipedia.org/w/index.php?title=Tortang_kamote&action=edit&redlink=1"


def test_links_local_html_excludes_tracking_urls(capsys):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp_html:
        temp_html.write(
            b"""<a href="https://www.googletagmanager.com/gtag/js">Google tag manager</a>
<a href="https://www.google-analytics.com/g/collect?v=2">Google Analytics</a>
<link href="https://fonts.googleapis.com/css2?family=Roboto" rel="stylesheet">
<link href="https://fonts.gstatic.com/s/roboto/v30/foo.woff2" rel="preload">
<a href="https://example.com/document.pdf">Document</a>"""
        )
        temp_html.flush()

        lb(["extract-links", "--local-html", temp_html.name])

    captured = capsys.readouterr().out.replace("\n", "")
    assert captured == "https://example.com/document.pdf"


def test_links_download_image_safe_loads_gallery_lazily(crawl_server, monkeypatch):
    """`links-download --image --safe` is database-less and must lazily load gallery-dl before
    the is_supported check, rather than raising because it was never pre-loaded."""
    from library.download import download as download_mod

    gallery_backend = download_mod.gallery_backend
    monkeypatch.delattr(gallery_backend.is_supported, "configured", raising=False)

    loaded = {"n": 0}

    def fake_load(_args):
        loaded["n"] += 1
        gallery_backend.is_supported.configured = True

    monkeypatch.setattr(gallery_backend, "gallery_dl_available", lambda: True)
    monkeypatch.setattr(gallery_backend, "load_module_level_gallery_dl", fake_load)
    monkeypatch.setattr(gallery_backend, "is_supported", lambda url: url.endswith(".png"))

    downloaded = []
    monkeypatch.setattr(gallery_backend, "download", lambda _args, m: downloaded.append(m["path"]))

    lb(["links-download", "--image", "--safe", "-R", crawl_server, "--path-exclude", "*/tag/*"])

    assert downloaded == [f"{crawl_server}img.png"]
    assert loaded["n"] == 1


def test_extract_links_recursive(crawl_server, capsys):
    lb(["extract-links", "-R", crawl_server, "--path-exclude", "*/tag/*"])

    out = set(capsys.readouterr().out.split())
    assert f"{crawl_server}a.html" in out
    assert f"{crawl_server}sub/b.html" in out
    assert f"{crawl_server}sub/c.html" in out
    assert f"{crawl_server}img.png" in out
    assert "https://external.example.com/x" in out
    assert f"{crawl_server}tag/deep.html" not in out


def test_extract_links_recursive_only_spiders_within_parent(crawl_server, capsys):
    # a link to a page in a sibling directory is downloaded but not followed
    lb(["extract-links", "-R", f"{crawl_server}sub/b.html", "--path-exclude", "*/tag/*"])

    out = set(capsys.readouterr().out.split())
    assert f"{crawl_server}a.html" in out  # yielded (downloaded) from sub/b.html
    assert f"{crawl_server}sub/c.html" in out  # within parent, followed
    assert f"{crawl_server}index.html" not in out  # sibling of the seed parent is not followed


def test_extract_links_not_recursive_is_single_page(crawl_server, capsys):
    lb(["extract-links", crawl_server])

    out = set(capsys.readouterr().out.split())
    assert f"{crawl_server}a.html" in out
    assert f"{crawl_server}sub/b.html" not in out


def test_extract_links_glob_include(crawl_server, capsys):
    lb(["extract-links", crawl_server, "--path-include", "*/a.html"])

    out = capsys.readouterr().out.split()
    assert out == [f"{crawl_server}a.html"]


def wayback_snapshot(timestamp, url):
    return f"https://web.archive.org/web/{timestamp}id_/{url}"


def test_parse_inner_urls_resolves_relative_wayback_links():
    # Wayback replays rewrite links as root-relative /web/<ts>/<original>. These must resolve
    # against the archive (not the original host, which may no longer be online).
    base = wayback_snapshot("2020", "https://example.com/dir/page.html")
    markup = b'<a href="/web/2021/https://example.com/dir/other.html">other</a><a href="sibling.html">s</a>'
    args = SimpleNamespace(
        stop_text=None,
        href=True,
        src=False,
        url=False,
        data_src=False,
        srcset=False,
        data_srcset=False,
        url_renames={},
        case_sensitive=True,
        strict_include=False,
        strict_exclude=False,
        path_include=[],
        path_exclude=[],
        text_exclude=[],
        text_include=[],
        before_exclude=[],
        before_include=[],
        after_exclude=[],
        after_include=[],
    )

    links = [d["link"] for d in extract_links.parse_inner_urls(args, base, markup)]

    assert links[0] == "https://web.archive.org/web/2021/https://example.com/dir/other.html"
    # a (rare) un-rewritten relative link stays inside the archive; the mangled embedded
    # original is left as-is and only collapsed in the dedup key (wayback_normalize)
    assert links[1] == "https://web.archive.org/web/2020id_/https:/example.com/dir/sibling.html"


def test_extract_links_webcache(monkeypatch, capsys):
    captured = {}

    class FakeFetcher:
        def __init__(self, source=None):
            captured["source"] = source

        def iter(self, _query, **kwargs):
            captured["query"] = _query
            captured["limit"] = kwargs.get("limit")
            yield {"url": "https://example.com/docs/a.html", "timestamp": "20200101000000", "mime": "text/html"}
            yield {"url": "https://example.com/docs/b.pdf", "timestamp": "20200101000000", "mime": "application/pdf"}

    monkeypatch.setattr(web, "cdx_toolkit", SimpleNamespace(CDXFetcher=FakeFetcher))

    lb(["extract-links", "--webcache", "https://example.com/docs/page.html"])

    out = capsys.readouterr().out.split()
    assert captured["source"] == "ia"
    assert captured["query"] == "example.com/docs/*"
    assert out == [
        wayback_snapshot("20200101000000", "https://example.com/docs/a.html"),
        wayback_snapshot("20200101000000", "https://example.com/docs/b.pdf"),
    ]


def test_extract_links_webcache_cc_source(monkeypatch, capsys):
    class FakeFetcher:
        def __init__(self, source=None):
            assert source == "cc"

        def iter(self, _query, **_kwargs):
            yield {"url": "https://example.com/docs/a.html", "timestamp": "20200101000000", "mime": "text/html"}

    monkeypatch.setattr(web, "cdx_toolkit", SimpleNamespace(CDXFetcher=FakeFetcher))

    lb(["extract-links", "--webcache", "--webcache-source", "cc", "https://example.com/docs/page.html"])

    out = capsys.readouterr().out.split()
    assert out == ["https://example.com/docs/a.html"]


def test_extract_links_webcache_time_range(monkeypatch, capsys):
    captured = {}

    class FakeFetcher:
        def __init__(self, source=None):
            pass

        def iter(self, _query, **kwargs):
            captured["from_ts"] = kwargs.get("from_ts")
            captured["to"] = kwargs.get("to")
            yield {"url": "https://example.com/docs/a.html", "timestamp": "20200101000000", "mime": "text/html"}

    monkeypatch.setattr(web, "cdx_toolkit", SimpleNamespace(CDXFetcher=FakeFetcher))

    lb(["extract-links", "--webcache", "--webcache-from", "2020", "--webcache-to", "2021", "https://example.com/docs/page.html"])

    out = capsys.readouterr().out.split()
    assert captured["from_ts"] == "2020"
    assert captured["to"] == "2021"
    assert out == [wayback_snapshot("20200101000000", "https://example.com/docs/a.html")]


def test_extract_links_webcache_recursive(monkeypatch, capsys):
    seed = "https://example.com/docs/page.html"
    b_page = "https://example.com/docs/b.html"
    c_page = "https://example.com/docs/c.html"
    external = "https://other.com/x.html"

    class FakeFetcher:
        def __init__(self, source=None):
            pass

        def iter(self, _query, **_kwargs):
            yield {"url": seed, "timestamp": "2020", "mime": "text/html"}
            yield {"url": b_page, "timestamp": "2020", "mime": "text/html"}

    pages = {
        wayback_snapshot("2020", seed): [
            {"link": wayback_snapshot("2021", seed), "mime": "text/html"},  # tarpit: same page, newer timestamp
            {"link": wayback_snapshot("2020", c_page), "mime": "text/html"},  # sibling, different timestamp
            {"link": wayback_snapshot("2020", external), "mime": "text/html"},  # out of scope
        ],
        wayback_snapshot("2020", b_page): [],
    }

    def fake_get_inner_urls(_args, url):
        return iter(pages.get(url, []))

    monkeypatch.setattr(web, "cdx_toolkit", SimpleNamespace(CDXFetcher=FakeFetcher))
    monkeypatch.setattr(extract_links, "get_inner_urls", fake_get_inner_urls)

    lb(["extract-links", "--webcache", "--recursive", seed])

    out = set(capsys.readouterr().out.split())
    assert wayback_snapshot("2020", seed) in out
    assert wayback_snapshot("2020", b_page) in out
    assert wayback_snapshot("2020", c_page) in out
    assert wayback_snapshot("2020", external) in out
    assert wayback_snapshot("2021", seed) not in out  # different timestamp of the same page is not re-downloaded


def test_crawl_wayback_follows_siblings_but_not_tarpit(monkeypatch):
    seed = "https://web.archive.org/web/2020/https://example.com/dir/page.html"
    sibling = "https://web.archive.org/web/2020/https://example.com/dir/sibling.html"
    same_page_newer = "https://web.archive.org/web/2021/https://example.com/dir/page.html"
    external = "https://web.archive.org/web/2020/https://other.com/x.html"

    responses = {
        seed: [
            {"link": sibling, "mime": "text/html"},
            {"link": same_page_newer, "mime": "text/html"},
            {"link": external, "mime": "text/html"},
        ],
        sibling: [{"link": "https://web.archive.org/web/2022/https://example.com/dir/page.html", "mime": "text/html"}],
    }

    def fake_get_inner_urls(_args, url):
        return iter(responses.get(url, []))

    monkeypatch.setattr(extract_links, "get_inner_urls", fake_get_inner_urls)

    args = SimpleNamespace(local_html=True, webcache=False)
    out = [d["link"] for d in extract_links.crawl(args, [seed])]

    assert out == [sibling, external]


def test_crawl_wayback_dedupes_scheme_mangled_urls(monkeypatch):
    seed = "https://web.archive.org/web/2020id_/https://example.com/dir/page.html"
    mangled = "https://web.archive.org/web/2021id_/https:/example.com/dir/other.html"
    clean = "https://web.archive.org/web/2022id_/https://example.com/dir/other.html"

    responses = {seed: [{"link": mangled, "mime": "text/html"}, {"link": clean, "mime": "text/html"}]}

    def fake_get_inner_urls(_args, url):
        return iter(responses.get(url, []))

    monkeypatch.setattr(extract_links, "get_inner_urls", fake_get_inner_urls)

    args = SimpleNamespace(local_html=True, webcache=False)
    out = [d["link"] for d in extract_links.crawl(args, [seed])]

    # https:/example.com and https://example.com are the same page: only one is downloaded
    assert len(out) == 1
    assert extract_links.dedup_key(out[0]) == "https://example.com/dir/other.html"


def _patch_backend_routing(monkeypatch):
    """Monkeypatch the download backends to record which URL each one receives."""
    from library.download import download as download_mod

    monkeypatch.setattr(download_mod.tube_backend, "is_supported", lambda url: url.endswith("clip"))
    monkeypatch.setattr(download_mod.gallery_backend, "load_module_level_gallery_dl", lambda _args: None)
    monkeypatch.setattr(download_mod.gallery_backend, "is_supported", lambda url: url.endswith("pic"))

    routed = {"tube": [], "gallery": [], "builtin": []}
    monkeypatch.setattr(download_mod.tube_backend, "download", lambda _args, m: routed["tube"].append(m["path"]))
    monkeypatch.setattr(download_mod.gallery_backend, "download", lambda _args, m: routed["gallery"].append(m["path"]))
    monkeypatch.setattr(extract_links.web, "download_link", lambda _args, url: routed["builtin"].append(url))
    return routed


def test_links_download_routes_by_profile(monkeypatch):
    routed = _patch_backend_routing(monkeypatch)
    args = SimpleNamespace(profile=DBType.auto, direct=False, safe=False, prefix=".", verbose=0)
    cache = {}

    for url in ["https://x/clip", "https://x/pic", "https://x/raw.html"]:
        extract_links._download_one(args, url, cache)  # ruff: ignore[private-member-access]

    assert routed["tube"] == ["https://x/clip"]
    assert routed["gallery"] == ["https://x/pic"]
    assert routed["builtin"] == ["https://x/raw.html"]


def test_links_download_explicit_profile_skips_resolution(monkeypatch):
    routed = _patch_backend_routing(monkeypatch)
    args = SimpleNamespace(profile=DBType.filesystem, direct=False, safe=False, prefix=".", verbose=0)
    cache = {}

    extract_links._download_one(args, "https://x/clip", cache)  # ruff: ignore[private-member-access]

    assert routed["tube"] == []
    assert routed["builtin"] == ["https://x/clip"]


def test_links_download_direct_uses_builtin(monkeypatch):
    """`links-download --direct` must bypass yt-dlp/gallery-dl routing even for a
    supported URL."""
    routed = _patch_backend_routing(monkeypatch)
    args = SimpleNamespace(profile=DBType.auto, direct=True, safe=False, prefix=".", verbose=0)
    cache = {}

    extract_links._download_one(args, "https://x/clip", cache)  # ruff: ignore[private-member-access]

    assert routed["tube"] == []
    assert routed["gallery"] == []
    assert routed["builtin"] == ["https://x/clip"]


def test_links_download_safe_skips_unsafe_links(monkeypatch):
    routed = _patch_backend_routing(monkeypatch)
    args = SimpleNamespace(profile=DBType.auto, direct=False, safe=True, prefix=".", verbose=0)
    cache = {}

    for url in ["https://x/clip", "https://x/raw.html"]:
        extract_links._download_one(args, url, cache)  # ruff: ignore[private-member-access]

    assert routed["tube"] == ["https://x/clip"]
    assert routed["builtin"] == []


def test_links_download_prints_downloaded_paths(monkeypatch, capsys):
    monkeypatch.setattr(extract_links.web, "download_link", lambda _args, _url: "/downloads/file.html")
    args = SimpleNamespace(
        profile=DBType.filesystem,
        direct=True,
        safe=False,
        prefix=".",
        verbose=1,
    )

    extract_links._download_one(args, "https://x/raw.html", {})  # ruff: ignore[private-member-access]

    assert capsys.readouterr().out.splitlines() == ["/downloads/file.html"]


def test_builtin_download_propagates_failures(monkeypatch):
    def fail(_args, _url):
        raise OSError("destination is not writable")

    monkeypatch.setattr(extract_links.web, "download_link", fail)

    with pytest.raises(OSError, match="destination is not writable"):
        extract_links._builtin_download(SimpleNamespace(), "https://example.com/file")  # ruff: ignore[private-member-access]
