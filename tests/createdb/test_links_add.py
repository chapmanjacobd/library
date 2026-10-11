from library.__main__ import library as lb
from tests.utils import connect_db_args


def test_links_add(temp_db):
    db1 = temp_db()
    lb(
        [
            "links-add",
            db1,
            "https://arxiv.org/list/cs/recent?skip=0&show=25",
            "--page-key=skip",
            "--page-start=0",
            "--page-step=25",
            "--path-include=/pdf/",
            "--max-pages=2",
        ]
    )

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) >= 30
    assert all("/pdf/" in d["path"] for d in media)


def test_links_add_recursive(temp_db, crawl_server):
    db1 = temp_db()
    lb(["links-add", db1, "--recursive", crawl_server, "--path-exclude", "*/tag/*"])

    args = connect_db_args(db1)
    media = {d["path"] for d in args.db.query("SELECT path FROM media")}

    assert f"{crawl_server}a.html" in media
    assert f"{crawl_server}sub/b.html" in media
    assert f"{crawl_server}sub/c.html" in media
    assert "https://external.example.com/x" in media
    assert f"{crawl_server}tag/deep.html" not in media
