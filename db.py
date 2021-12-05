import sqlite3
from rich.traceback import install

install()

con = sqlite3.connect("./videos.db")
con.row_factory = sqlite3.Row


def fetchall_dict(*args):
    return [dict(r) for r in con.execute(*args).fetchall()]


def singleColumnToList(array_of_half_tuplets, column_name=1):
    return list(
        map(
            lambda x: x[column_name],
            array_of_half_tuplets,
        )
    )
