import argparse
import re
import sqlite3
from collections import defaultdict

from library import usage
from library.utils import argparse_utils, nums, printing, strings

VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.stats_words)
    parser.add_argument("database", help="SQLite database to query")
    parser.add_argument("table", nargs="?", default="media", help="Table containing path and size columns")
    args = parser.parse_args()
    if not VALID_IDENTIFIER.fullmatch(args.table):
        parser.error(f"invalid table name: {args.table!r}")
    return args


def word_stats(database: str, table: str = "media") -> list[dict]:
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        missing = {"path", "size"} - columns
        if missing:
            missing_columns = ", ".join(sorted(missing))
            message = f"{table!r} is missing required columns: {missing_columns}"
            raise ValueError(message)

        where = " WHERE COALESCE(time_deleted, 0) = 0" if "time_deleted" in columns else ""
        groups = defaultdict(list)
        query = f"SELECT path, size FROM {table}{where}"  # noqa: S608 - table is validated above
        for path, size in conn.execute(query):
            if path and size is not None:
                sentence = strings.path_to_sentence(path)
                for word in set(sentence.split()):
                    groups[word].append(size)
    finally:
        conn.close()

    results = []
    for word, sizes in groups.items():
        total = sum(sizes)
        median = nums.safe_median(sizes) or 0
        results.append(
            {
                "name": word,
                "total": strings.file_size(total),
                "median": strings.file_size(median),
                "count": len(sizes),
                "_total": total,
            }
        )

    results.sort(key=lambda row: row["_total"])
    for row in results:
        row.pop("_total")
    return results


def stats_words() -> None:
    args = parse_args()
    printing.table(word_stats(args.database, args.table))
