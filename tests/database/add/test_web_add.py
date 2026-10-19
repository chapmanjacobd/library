from types import SimpleNamespace

import pytest

from library.__main__ import library as lb
from library.database.add import web_add
from library.utils import nums
from library.utils.consts import DBType
from tests.utils import connect_db_args


@pytest.mark.skip("CloudFlare bot blocking...")
def test_web_add(temp_db):
    db1 = temp_db()
    lb(["web-add", "--fs", db1, "https://unli.xyz/proliferation/"])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) >= 4


@pytest.mark.parametrize(
    ("after_text", "expected"),
    [
        ("02-Sep-2017 01:28 125K", nums.human_to_bytes("125K")),
        ("10-May-2016 19:12 23M", nums.human_to_bytes("23M")),
        ("10-May-2016 19:12 1.5 GiB", nums.human_to_bytes("1.5 GiB")),
        ("14-Feb-2013 16:34 480", 480),
        ("28-Feb-2021 09:44 -", None),
        ("10-May-2016 19:12", None),
        ("unrelated text", None),
    ],
)
def test_extract_html_size(after_text, expected):
    assert web_add.extract_html_size({"after_text": after_text}) == expected


def test_add_basic_metadata_keeps_html_size_without_content_length(monkeypatch):
    args = SimpleNamespace(profiles=[DBType.filesystem], hash=False, sleep_interval_requests=0)
    monkeypatch.setattr(web_add.web, "stat", lambda _path: SimpleNamespace(st_size=0, st_mtime=123))
    monkeypatch.setattr(web_add.file_utils, "detect_mimetype", lambda _path: "application/octet-stream")

    media = web_add.add_basic_metadata(args, {"path": "https://example.com/file.bin", "size": 125 * 1024})

    assert media["size"] == 125 * 1024


def test_spider_follows_html_descendants_and_skips_known_pages(monkeypatch):
    root = "https://example.com/root/"
    page_a = f"{root}a.html"
    page_b = f"{root}sub/b.html"
    page_leaf = f"{root}sub/leaf.html"
    known_page = f"{root}known.html"
    sibling = f"{root}sibling.html"
    asset = f"{root}asset.bin"
    asset_a = f"{root}a.bin"
    outside = "https://other.example.com/file.bin"

    pages = {
        root: [
            {"link": page_a},
            {"link": page_b},
            {"link": known_page},
            {"link": asset},
            {"link": outside},
        ],
        page_a: [{"link": asset_a}],
        page_b: [{"link": page_leaf}, {"link": sibling}],
        page_leaf: [],
        known_page: [{"link": f"{known_page}/child.html"}],
    }
    loaded = []
    added = []

    def get_inner_urls(_args, path):
        loaded.append(path)
        yield from pages[path]

    args = SimpleNamespace(
        media=False,
        threads=1,
        force=False,
        verbose=0,
        profiles=[],
        hash=False,
        sizes=None,
        scan_all_files=False,
    )
    monkeypatch.setattr(web_add.extract_links, "get_inner_urls", get_inner_urls)
    monkeypatch.setattr(web_add.web, "is_html", lambda _args, path: path in pages)
    monkeypatch.setattr(web_add.web, "sleep", lambda _args: None)
    monkeypatch.setattr(web_add.db_media, "exists", lambda _args, path: path == known_page)
    monkeypatch.setattr(web_add, "add_extra_metadata", lambda _args, media: media)
    monkeypatch.setattr(web_add, "add_media", lambda _args, media: added.extend(media))

    new_media_count = web_add.spider(args, [root])

    assert new_media_count == 4
    assert set(loaded) == {root, page_a, page_b, page_leaf}
    assert {media["path"] for media in added} == {asset, asset_a, outside, sibling}


def test_spider_media_mode_batches_paths_without_loading_pages(monkeypatch):
    paths = ["https://example.com/a.mp4", "https://example.com/b.mp4"]
    added = []
    loaded = []
    args = SimpleNamespace(
        media=True,
        threads=1,
        force=False,
        verbose=0,
        profiles=[],
        hash=False,
        sizes=None,
        scan_all_files=False,
    )

    monkeypatch.setattr(web_add.extract_links, "get_inner_urls", lambda _args, path: loaded.append(path))
    monkeypatch.setattr(web_add.web, "sleep", lambda _args: None)
    monkeypatch.setattr(web_add.db_media, "exists", lambda _args, path: path == paths[0])
    monkeypatch.setattr(web_add, "add_extra_metadata", lambda _args, media: media)
    monkeypatch.setattr(web_add, "add_media", lambda _args, media: added.extend(media))

    new_media_count = web_add.spider(args, paths.copy())

    assert new_media_count == 1
    assert loaded == []
    assert {media["path"] for media in added} == {paths[1]}
