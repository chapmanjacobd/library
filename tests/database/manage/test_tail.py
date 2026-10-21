import sqlite3

from library.database.manage import tail


def test_tail_polls_rowid_and_without_rowid_tables():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE ordinary (value TEXT)")
    connection.execute("CREATE TABLE keyed (id INTEGER PRIMARY KEY, value TEXT) WITHOUT ROWID")
    connection.execute("CREATE TABLE composite (left TEXT, right TEXT, PRIMARY KEY(left, right)) WITHOUT ROWID")
    connection.execute("INSERT INTO ordinary VALUES ('old')")
    connection.execute("INSERT INTO keyed VALUES (1, 'old')")
    connection.commit()

    cursors = tail.get_initial_cursors(connection)
    assert set(cursors) == {"ordinary", "keyed"}
    connection.execute("INSERT INTO ordinary VALUES ('new')")
    connection.execute("INSERT INTO keyed VALUES (2, 'new')")
    connection.commit()
    updated, events = tail.tail_once(connection, cursors)

    assert {(event["table"], event["key"], event["row"]["value"]) for event in events} == {
        ("ordinary", 2, "new"),
        ("keyed", 2, "new"),
    }
    assert updated["keyed"]["value"] == 2
    connection.close()
