import pytest

from library.__main__ import library as lb
from library.createdb.tube_add import tube_add
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
