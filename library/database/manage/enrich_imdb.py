"""Fill media database metadata from cached IMDb datasets."""

import argparse
import csv
import gzip
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

from library.database.manage._readonly import quote_identifier, table_info, table_names, validate_identifier
from library.utils import argparse_utils, printing
from library.utils.log_utils import log

CACHE_SUBDIR = "imdb"
BASE_URL = "https://datasets.imdbws.com/"
DATASET_FILES = {
    "basics": "title.basics.tsv.gz",
    "akas": "title.akas.tsv.gz",
    "ratings": "title.ratings.tsv.gz",
}
INDEX_DB = "imdb_index.db"
STAMP_FILE = "imdb_index.stamp"
ENRICH_COLUMNS = ("genre", "title", "imdb_rating", "imdb_votes", "year")
MIN_TITLE_LENGTH = 3
HTTP_OK = 200
MAX_YEAR_DISTANCE = 3
MAX_SERIES_YEAR_DISTANCE = 2
EXTRA_CODEC_EXTENSIONS = {".av1", ".h264", ".x264", ".x265", ".265", ".264", ".vp9", ".hevc"}
RELEASE_TAGS = (
    r"720p|1080p|2160p|4k|8k|x264|x265|h264|h265|av1|hevc|vp9|"
    r"web.?dl|webrip|bluray|blu-ray|brrip|brip|hdtv|dvdrip|dvd|remux|"
    r"yify|oldtoons?|nf|netflix|disney\+|amzn|amazon|hulu|atvp|apple.?tv|"
    r"multisub|multilingual|dubbed|proper|repack|imax|extended|unrated|directors?\.?cut"
)
EPISODE_RE = re.compile(r"(?i)(?:^|[^a-z0-9])(s\d{1,2}(?:e\d{1,4})?)(?=[^a-z0-9]|$)")
YEAR_RE = re.compile(r"\b(18|19|20)\d{2}\b")
NONALNUM_RE = re.compile(r"[^a-z0-9]+")
ARTICLE_RE = re.compile(r"^(the|a|an)\s+")


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / CACHE_SUBDIR


def norm(value: str | None) -> str:
    if not value:
        return ""
    return NONALNUM_RE.sub(" ", value.lower()).strip()


def norm_short(value: str | None) -> str:
    return norm(ARTICLE_RE.sub("", norm(value)))


def parse_tsv(path: str | Path, columns: dict[str, str]):
    csv.field_size_limit(sys.maxsize)
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.reader(file, delimiter="\t")
        header = next(reader, None)
        if header is None:
            return
        positions = {columns[name]: index for index, name in enumerate(header) if name in columns}
        for row in reader:
            if not row:
                continue
            yield {
                name: (None if index >= len(row) or row[index] == r"\N" else row[index])
                for name, index in positions.items()
            }


def _download(url: str, destination: Path) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url)  # noqa: S310 - URL is a fixed IMDb HTTPS endpoint
    if offset:
        request.add_header("Range", f"bytes={offset}-")

    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - URL is a fixed IMDb HTTPS endpoint
        if response.status == HTTP_OK and offset:
            partial.write_bytes(b"")
            offset = 0
        with partial.open("ab") as file:
            while chunk := response.read(1024 * 256):
                file.write(chunk)
    partial.replace(destination)


def dataset_paths(*, refresh: bool = False, max_age: int = 0) -> dict[str, Path]:
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, filename in DATASET_FILES.items():
        destination = directory / filename
        stale = max_age > 0 and destination.exists() and time.time() - destination.stat().st_mtime > max_age * 86400
        if refresh or stale:
            destination.unlink(missing_ok=True)
        if not destination.exists():
            log.info("Downloading %s", filename)
            _download(BASE_URL + filename, destination)
        paths[key] = destination
    return paths


def _dataset_stamp(paths: dict[str, Path]) -> str:
    return " ".join(f"{path.stat().st_mtime_ns}:{path.stat().st_size}" for path in paths.values())


def build_index(paths: dict[str, Path], *, rebuild: bool = False) -> Path:
    directory = next(iter(paths.values())).parent
    index_path = directory / INDEX_DB
    stamp_path = directory / STAMP_FILE
    stamp = _dataset_stamp(paths)
    existing_stamp = stamp_path.read_text().strip() if stamp_path.exists() else ""
    if index_path.exists() and not rebuild and existing_stamp == stamp:
        log.info("Using cached IMDb index.")
        return index_path

    for path in (index_path, Path(f"{index_path}-journal"), Path(f"{index_path}-wal")):
        path.unlink(missing_ok=True)
    log.info("Building local IMDb index.")
    connection = sqlite3.connect(index_path)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE titles (
                tconst TEXT PRIMARY KEY,
                title_type TEXT,
                primary_title TEXT,
                original_title TEXT,
                norm_title TEXT,
                norm_original TEXT,
                start_year INTEGER,
                genres TEXT,
                rating REAL,
                votes INTEGER
            );
            CREATE TABLE akas (tconst TEXT, norm_title TEXT);
            """
        )
        ratings = {}
        for row in parse_tsv(
            paths["ratings"],
            {"tconst": "tconst", "averageRating": "rating", "numVotes": "votes"},
        ):
            try:
                ratings[row["tconst"]] = (float(row["rating"]), int(row["votes"]))
            except (TypeError, ValueError):
                continue

        title_rows = []
        for row in parse_tsv(
            paths["basics"],
            {
                "tconst": "tconst",
                "titleType": "title_type",
                "primaryTitle": "primary_title",
                "originalTitle": "original_title",
                "startYear": "start_year",
                "genres": "genres",
            },
        ):
            rating, votes = ratings.get(row.get("tconst"), (None, None))
            try:
                year = int(row["start_year"]) if row.get("start_year") else None
            except ValueError:
                year = None
            title_rows.append(
                (
                    row.get("tconst"),
                    row.get("title_type"),
                    row.get("primary_title"),
                    row.get("original_title"),
                    norm(row.get("primary_title")),
                    norm(row.get("original_title")),
                    year,
                    row.get("genres"),
                    rating,
                    votes,
                )
            )
        connection.executemany("INSERT INTO titles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", title_rows)

        aka_rows = [
            (row.get("tconst"), norm(row.get("title")))
            for row in parse_tsv(paths["akas"], {"titleId": "tconst", "title": "title"})
            if row.get("title")
        ]
        connection.executemany("INSERT INTO akas VALUES (?, ?)", aka_rows)
        connection.executescript(
            "CREATE INDEX idx_titles_norm ON titles(norm_title);"
            "CREATE INDEX idx_titles_original ON titles(norm_original);"
            "CREATE INDEX idx_akas_norm ON akas(norm_title);"
        )
        connection.commit()
    finally:
        connection.close()
    stamp_path.write_text(stamp)
    return index_path


def _clean_title(value: str) -> str:
    value = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", value)
    value = value.replace("_", " ").replace(".", " ").replace("-", " ")
    value = re.sub(r"(?i)\b(" + RELEASE_TAGS + r")\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_title(value: str | None) -> str:
    value = (value or "").replace("_", " ")
    value = re.split(r"\s+[-–—|]\s+|\s+[-–—|]|\s+\|\s+", value, maxsplit=1)[0]
    match = YEAR_RE.search(value)
    if match:
        value = value[: match.start()]
    return _clean_title(value)


def parse_filename(path: str | Path) -> tuple[str, int | None, bool, str | None]:
    path = Path(path)
    stem = path.stem
    while Path(stem).suffix.lower() in EXTRA_CODEC_EXTENSIONS:
        suffix = Path(stem).suffix
        stem = stem[: -len(suffix)]

    parts = EPISODE_RE.split(stem)
    is_episode = len(parts) >= MIN_TITLE_LENGTH
    series_part = parts[0] if is_episode else None
    episode_part = " ".join(parts[2:]) if is_episode else stem
    year = None
    parent_year = YEAR_RE.search(path.parent.name.replace("_", " "))
    media_year = YEAR_RE.search(episode_part.replace("_", " "))
    if parent_year:
        year = int(parent_year.group())
    if media_year:
        year = int(media_year.group())
    title = extract_title(episode_part)
    series = extract_title(series_part) if series_part else None
    return title, year, is_episode, series


def _best_title(
    connection: sqlite3.Connection,
    title: str,
    year: int | None,
    *,
    is_episode: bool,
) -> dict | None:
    normalized = norm(title)
    if len(normalized) < MIN_TITLE_LENGTH:
        return None
    candidates = list(
        connection.execute(
            "SELECT * FROM titles WHERE norm_title = ? OR norm_original = ?",
            (normalized, normalized),
        )
    )
    candidates.extend(
        connection.execute(
            "SELECT t.* FROM akas a JOIN titles t ON t.tconst = a.tconst WHERE a.norm_title = ?",
            (normalized,),
        )
    )
    best = None
    best_score = float("-inf")
    for row in candidates:
        score = 100 if row["norm_title"] == normalized else 60
        if is_episode:
            score += 15 if row["title_type"] in ("tvEpisode", "tvSeries", "tvMiniSeries") else 0
        else:
            score += 10 if row["title_type"] in ("movie", "tvMovie", "video", "short") else 0
        if year and row["start_year"]:
            difference = abs(row["start_year"] - year)
            score += 50 if difference == 0 else 25 if difference <= 1 else 5 if difference <= MAX_YEAR_DISTANCE else -20
        score += min(row["votes"] or 0, 100000) / 20000
        if score > best_score:
            best, best_score = dict(row), score
    return best


def _best_series(connection: sqlite3.Connection, title: str | None, year: int | None) -> dict | None:
    normalized = norm(title)
    if len(normalized) < MIN_TITLE_LENGTH:
        return None
    best = None
    best_score = float("-inf")
    for row in connection.execute(
        "SELECT * FROM titles WHERE (norm_title = ? OR norm_original = ?) "
        "AND title_type IN ('tvSeries', 'tvMiniSeries', 'tvMovie')",
        (normalized, normalized),
    ):
        score = 0
        if year and row["start_year"]:
            difference = abs(row["start_year"] - year)
            score += 50 if difference == 0 else 25 if difference <= MAX_SERIES_YEAR_DISTANCE else 5
        score += min(row["votes"] or 0, 100000) / 20000
        if score > best_score:
            best, best_score = dict(row), score
    return best


def _is_empty(value, column: str) -> bool:
    if value is None:
        return True
    if column in ("year", "imdb_votes"):
        return value == 0
    return str(value).strip() == ""


def _target_details(connection: sqlite3.Connection, table: str) -> tuple[set[str], str, str]:
    validate_identifier(table, label="table name")
    if table not in table_names(connection):
        message = f"table not found: {table!r}"
        raise ValueError(message)
    columns = {row["name"] for row in table_info(connection, table)}
    path_column = "path" if "path" in columns else "webpath" if "webpath" in columns else None
    if path_column is None:
        message = f"{table!r} has neither a path nor webpath column"
        raise ValueError(message)
    id_column = "id" if "id" in columns else "rowid"
    if id_column == "rowid":
        try:
            connection.execute(f"SELECT rowid FROM {quote_identifier(table)} LIMIT 0")  # noqa: S608 - table is validated
        except sqlite3.OperationalError as exc:
            message = f"{table!r} needs an id column because it has no rowid"
            raise ValueError(message) from exc
    return columns, path_column, id_column


def enrich_database(  # noqa: PLR0912, PLR0915 - enrichment coordinates schema, index, and update phases
    database: str,
    *,
    table: str = "media",
    dry_run: bool = False,
    force: bool = False,
    refresh: bool = False,
    rebuild_index: bool = False,
    max_age: int = 0,
    verbose: bool = False,
) -> dict[str, int]:
    target = sqlite3.connect(database)
    target.row_factory = sqlite3.Row
    try:
        columns, path_column, id_column = _target_details(target, table)
        missing = {
            "genre": "TEXT",
            "title": "TEXT",
            "imdb_rating": "REAL",
            "imdb_votes": "INTEGER",
            "year": "INTEGER",
        }
        missing = {name: kind for name, kind in missing.items() if name not in columns}
        if not dry_run:
            for name, kind in missing.items():
                target.execute(f"ALTER TABLE {quote_identifier(table)} ADD COLUMN {quote_identifier(name)} {kind}")
            target.commit()
            columns.update(missing)

        paths = dataset_paths(refresh=refresh, max_age=max_age)
        index_path = build_index(paths, rebuild=rebuild_index)
        index = sqlite3.connect(index_path)
        index.row_factory = sqlite3.Row
        try:
            selected = [
                f"{quote_identifier(id_column)} AS rid" if id_column != "rowid" else "rowid AS rid",
                f"{quote_identifier(path_column)} AS media_path",
            ]
            selected.extend(
                f"{quote_identifier(column)} AS {quote_identifier(column)}"
                if column in columns
                else f"NULL AS {quote_identifier(column)}"
                for column in ENRICH_COLUMNS
            )
            rows = list(
                target.execute(f"SELECT {', '.join(selected)} FROM {quote_identifier(table)}")  # noqa: S608 - identifiers are validated
            )
            counts = dict.fromkeys(ENRICH_COLUMNS, 0)
            updates = []
            for row in rows:
                existing = dict(row)
                if not force and all(not _is_empty(existing[column], column) for column in ENRICH_COLUMNS):
                    continue
                title, year, is_episode, series = parse_filename(existing["media_path"] or "")
                title = title or extract_title(existing.get("title"))
                match = _best_title(index, title, year, is_episode=is_episode)
                if match is None and title:
                    match = _best_title(index, norm_short(title), year, is_episode=is_episode)
                series_match = _best_series(index, series, year) if is_episode else None
                if match is None:
                    match = series_match
                if match is None:
                    if verbose:
                        log.info("No IMDb match for %r", title)
                    continue
                values = {
                    "genre": match.get("genres"),
                    "title": match.get("primary_title"),
                    "imdb_rating": match.get("rating"),
                    "imdb_votes": match.get("votes"),
                    "year": match.get("start_year"),
                }
                changes = {
                    column: value
                    for column, value in values.items()
                    if value is not None and (force or _is_empty(existing[column], column))
                }
                if changes:
                    updates.append((changes, existing["rid"]))
                    for column in changes:
                        counts[column] += 1

            if dry_run:
                log.info("Dry run; no changes written.")
                return counts

            with target:
                for changes, row_id in updates:
                    assignments = ", ".join(f"{quote_identifier(column)} = ?" for column in changes)
                    query = (
                        f"UPDATE {quote_identifier(table)} SET {assignments} "  # noqa: S608 - identifiers are validated
                        f"WHERE {quote_identifier(id_column) if id_column != 'rowid' else 'rowid'} = ?"
                    )
                    target.execute(query, (*changes.values(), row_id))
            return counts
        finally:
            index.close()
    finally:
        target.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--db", dest="database_override", metavar="DATABASE")
    parser.add_argument("--table", default="media")
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true")
    parser.add_argument("--max-age", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    if args.database_override:
        args.database = args.database_override
    validate_identifier(args.table, label="table name")
    if args.max_age < 0:
        parser.error("--max-age must not be negative")
    return args


def enrich_imdb() -> None:
    args = parse_args()
    counts = enrich_database(
        args.database,
        table=args.table,
        dry_run=args.dry_run,
        force=args.force,
        refresh=args.refresh,
        rebuild_index=args.rebuild_index,
        max_age=args.max_age,
        verbose=args.verbose,
    )
    printing.table([{"column": column, "updated": count} for column, count in counts.items()])


def enrich() -> None:
    enrich_imdb()
