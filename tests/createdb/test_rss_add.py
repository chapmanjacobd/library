from xklb.createdb import rss_add


def test_get_rss_exists():
    feed = rss_add.get_feed("https://simonwillison.net/atom/everything/")

    assert feed.feed.title == "Simon Willison's Weblog"  # type: ignore


def test_get_rss_redirect():
    feed = rss_add.get_feed("https://micro.mjdescy.me/")

    assert feed.feed.title == "Michael Descy"  # type: ignore
