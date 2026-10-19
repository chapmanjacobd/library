import sqlite3

from library.database.manage.stats_words import word_stats


def test_word_stats_aggregates_unique_path_words_and_ignores_deleted(tmp_path):
    database = tmp_path / "media.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE media (path TEXT, size INTEGER, time_deleted INTEGER)")
    conn.executemany(
        "INSERT INTO media VALUES (?, ?, ?)",
        [
            ("/library/Science/Fiction/book.mkv", 100, 0),
            ("/library/Science/fiction/film.mkv", 300, 0),
            ("/library/Science/deleted.mkv", 900, 123),
        ],
    )
    conn.commit()
    conn.close()

    assert {row["name"]: row for row in word_stats(str(database))} == {
        "book": {"name": "book", "total": "100Bytes", "median": "100Bytes", "count": 1},
        "film": {"name": "film", "total": "300Bytes", "median": "300Bytes", "count": 1},
        "Fiction": {"name": "Fiction", "total": "100Bytes", "median": "100Bytes", "count": 1},
        "fiction": {"name": "fiction", "total": "300Bytes", "median": "300Bytes", "count": 1},
        "Science": {"name": "Science", "total": "400Bytes", "median": "200Bytes", "count": 2},
        "library": {"name": "library", "total": "400Bytes", "median": "200Bytes", "count": 2},
        "mkv": {"name": "mkv", "total": "400Bytes", "median": "200Bytes", "count": 2},
    }
