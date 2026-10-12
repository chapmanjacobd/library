from types import SimpleNamespace

import pytest

from library.__main__ import library as lb
from library.createdb import web_add
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
