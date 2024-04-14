from xklb import rss_extract


def test_get_rss_exists():
    feed = rss_extract.get_feed("https://simonwillison.net/atom/everything/")

    assert feed.feed.title == "Simon Willison's Weblog" # type: ignore


def test_get_rss_redirect():
    feed = rss_extract.get_feed("https://micro.mjdescy.me/")

    assert feed.feed.title == "Michael Descy" # type: ignore
