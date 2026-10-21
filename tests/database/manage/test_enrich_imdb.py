import gzip
import sqlite3

import pytest

from library.database.manage import enrich_imdb


def _write_tsv(path, header: list[str], rows: list[list[str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as file:
        file.write("\t".join(header) + "\n")
        for row in rows:
            file.write("\t".join(row) + "\n")


def test_imdb_enrichment_uses_cached_data_and_dry_run(tmp_path, monkeypatch):
    paths = {
        "basics": tmp_path / "title.basics.tsv.gz",
        "akas": tmp_path / "title.akas.tsv.gz",
        "ratings": tmp_path / "title.ratings.tsv.gz",
    }
    _write_tsv(
        paths["basics"],
        ["tconst", "titleType", "primaryTitle", "originalTitle", "startYear", "genres"],
        [["tt0133093", "movie", "The Matrix", "The Matrix", "1999", "Action,Sci-Fi"]],
    )
    _write_tsv(paths["akas"], ["titleId", "title"], [["tt0133093", "The Matrix"]])
    _write_tsv(paths["ratings"], ["tconst", "averageRating", "numVotes"], [["tt0133093", "8.7", "2000000"]])
    database = tmp_path / "media.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE media (id INTEGER PRIMARY KEY, path TEXT)")
    connection.execute("INSERT INTO media(path) VALUES (?)", ("The.Matrix.1999.mkv",))
    connection.commit()
    connection.close()
    monkeypatch.setattr(enrich_imdb, "dataset_paths", lambda **_kwargs: paths)

    counts = enrich_imdb.enrich_database(str(database), dry_run=True, rebuild_index=True)
    assert counts["title"] == 1
    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA table_info(media)").fetchall() == [
        (0, "id", "INTEGER", 0, None, 1),
        (1, "path", "TEXT", 0, None, 0),
    ]
    assert connection.execute("SELECT path FROM media").fetchone()[0] == "The.Matrix.1999.mkv"
    connection.close()

    enrich_imdb.enrich_database(str(database), rebuild_index=False)
    connection = sqlite3.connect(database)
    row = connection.execute("SELECT title, genre, imdb_rating, imdb_votes, year FROM media").fetchone()
    connection.close()
    assert row == ("The Matrix", "Action,Sci-Fi", 8.7, 2000000, 1999)


def test_imdb_helpers_are_lazy_and_validate_identifiers():
    assert enrich_imdb.parse_filename("The.Matrix.S01E02.1080p.mkv") == (
        "",
        None,
        True,
        "The Matrix",
    )
    with pytest.raises(ValueError, match="invalid table name"):
        enrich_imdb.parse_args(["media.db", "--table", "media;drop"])
