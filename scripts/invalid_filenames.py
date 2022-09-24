import argparse, shutil, sqlite3

import ftfy

from xklb import db
from xklb.utils import log

"""
hmm not sure what has caused this... hopefully this script can help

  File "/usr/lib64/python3.10/subprocess.py", line 2045, in _communicate
    stderr = self._translate_newlines(stderr,
  File "/usr/lib64/python3.10/subprocess.py", line 1029, in _translate_newlines
    data = data.decode(encoding, errors)
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc2 in position 183: invalid continuation byte
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.db = db.connect(args)
    return args


def get_paths(args):
    columns = args.db["media"].columns
    sql_filters = []
    if "is_deleted" in columns:
        sql_filters.append("AND is_deleted=0")
    if "is_downloaded" in columns:
        sql_filters.append("AND is_downloaded=1")

    db_resp = [
        d["path"] for d in args.db.query(f"select path from media where 1=1 {' '.join(sql_filters)} order by path")
    ]

    return db_resp


def rename_invalid_files() -> None:
    args = parse_args()
    paths = get_paths(args)

    christen_count = 0
    for p in paths:
        fixed = ftfy.fix_text(p, uncurl_quotes=False).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "")
        if p != fixed:
            log.info(p)
            log.info(fixed)
            try:
                args.db.execute("UPDATE media SET path=? where path=?", [fixed, p])
            except sqlite3.IntegrityError:
                log.warning("File already exists with that nice name")
            else:
                try:
                    shutil.move(p, fixed)
                except FileNotFoundError:
                    log.warning("FileNotFound. You should re-scan via fsadd %s", p)
                else:
                    christen_count += 1

    print("\nRenamed", christen_count, "files.")
    print("Anointed with the power of UTF-8 our hero returns to the radioactive wastes...")
    print("\nYou may want to run bfs to remove nested empty folders:\n")
    print(
        r"yes | bfs -nohidden -type d -exec bfs -f {} -not -type d -exit 1 \; -prune -ok bfs -f {} -type d -delete \;"
    )


if __name__ == "__main__":
    rename_invalid_files()
