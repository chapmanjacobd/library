import unittest

from library.utils import sql_utils


class TestStringComparison(unittest.TestCase):
    def test_compare_block_strings_starts_with(self):
        assert sql_utils.compare_block_strings("hello", "hello world")
        assert not sql_utils.compare_block_strings("world", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")

    def test_compare_block_strings_ends_with(self):
        assert sql_utils.compare_block_strings("%world", "hello world")
        assert sql_utils.compare_block_strings("hello", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")

    def test_compare_block_strings_contains(self):
        assert sql_utils.compare_block_strings("hello", "hello world")
        assert sql_utils.compare_block_strings("%world%", "hello world ok")
        assert sql_utils.compare_block_strings("hello world", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")

    def test_compare_block_strings_regex(self):
        assert sql_utils.compare_block_strings("he%o%", "hello world")
        assert sql_utils.compare_block_strings("%he%o%", " hello world")
        assert not sql_utils.compare_block_strings("%abc%", "hello world")
        assert sql_utils.compare_block_strings("h%o w%ld", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")
        assert sql_utils.compare_block_strings(None, None)
        assert not sql_utils.compare_block_strings(None, "hello world")
        assert not sql_utils.compare_block_strings("abc", None)


class TestBlocklist(unittest.TestCase):
    def setUp(self):
        self.media = [
            {"title": "Movie 1", "genre": "Action"},
            {"title": "Movie 2", "genre": "Comedy"},
            {"title": "Movie 3", "genre": "Drama"},
            {"title": "Movie 4", "genre": "Thriller"},
        ]

        self.blocklist = [{"genre": "Comedy"}, {"genre": "Thriller"}]

    def test_filter_dicts_genre(self):
        filtered_media = sql_utils.block_dicts_like_sql(self.media, self.blocklist)
        assert len(filtered_media) == 2
        assert {"title": "Movie 1", "genre": "Action"} in filtered_media
        assert {"title": "Movie 3", "genre": "Drama"} in filtered_media

    def test_filter_dicts_title(self):
        filtered_media = sql_utils.block_dicts_like_sql(self.media, [{"title": "Movie 1"}, {"title": "Movie 33"}])
        assert len(filtered_media) == 3
        assert {"title": "Movie 3", "genre": "Drama"} in filtered_media

    def test_filter_rows_with_substrings_contains(self):
        self.media.append({"title": "Movie 5", "genre": "Action Comedy"})
        filtered_media = sql_utils.block_dicts_like_sql(self.media, self.blocklist)
        assert len(filtered_media) == 3
        assert {"title": "Movie 5", "genre": "Action Comedy"} in filtered_media


class TestAllowlist(unittest.TestCase):
    def setUp(self):
        self.media = [
            {"title": "Movie 1", "genre": "Action"},
            {"title": "Movie 2", "genre": "Comedy"},
            {"title": "Movie 3", "genre": "Drama"},
            {"title": "Movie 4", "genre": "Thriller"},
        ]

        self.allowlist = [{"genre": "Comedy"}, {"genre": "Thriller"}]

    def test_filter_dicts_genre(self):
        filtered_media = sql_utils.allow_dicts_like_sql(self.media, self.allowlist)
        assert len(filtered_media) == 2

    def test_filter_dicts_title(self):
        filtered_media = sql_utils.allow_dicts_like_sql(self.media, [{"title": "Movie 1"}, {"title": "Movie 33"}])
        assert len(filtered_media) == 1

    def test_filter_rows_with_substrings_contains(self):
        self.media.append({"title": "Movie 5", "genre": "Action Comedy"})
        filtered_media = sql_utils.allow_dicts_like_sql(self.media, self.allowlist)
        assert len(filtered_media) == 2
        assert {"title": "Movie 5", "genre": "Action Comedy"} not in filtered_media
