import pytest

from library.__main__ import library as lb


@pytest.mark.parametrize(
    ("args", "stdout"),
    [
        (
            ["--batch-size=inf", "tests/data/test.xml", "tests/data/test2.xml"],
            """## Diff tests/data/test.xml:0 and tests/data/test2.xml:0

|    |   index |   A |   B |   C | _merge     |
|----|---------|-----|-----|-----|------------|
|  0 |       0 |   1 |   3 |   5 | left_only  |
|  1 |       1 |   2 |   4 |   6 | left_only  |
|  2 |       0 |   1 |   4 |   5 | right_only |
|  3 |       1 |   2 |   4 |   3 | right_only |

""",
        ),
    ],
)
def test_lb_incremental_diff(args, stdout, capsys):
    lb(["incremental-diff", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)


@pytest.mark.parametrize(
    ("suffix", "rows"),
    [
        (".csv", "id,value\n1,one\n2,two\n3,three\n"),
        (".jsonl", '{"id": 1, "value": "one"}\n{"id": 2, "value": "two"}\n{"id": 3, "value": "three"}\n'),
        (".json", '[{"id": 1, "value": "one"}, {"id": 2, "value": "two"}, {"id": 3, "value": "three"}]'),
    ],
)
def test_id_driven_diff_handles_reordered_streaming_inputs(tmp_path, suffix, rows, capsys):
    path1 = tmp_path / f"one{suffix}"
    path2 = tmp_path / f"two{suffix}"
    path1.write_text(rows)
    if suffix == ".csv":
        reordered = "id,value\n3,three\n1,one\n2,two\n"
    elif suffix == ".jsonl":
        reordered = '{"id": 3, "value": "three"}\n{"id": 1, "value": "one"}\n{"id": 2, "value": "two"}\n'
    else:
        reordered = '[{"id": 3, "value": "three"}, {"id": 1, "value": "one"}, {"id": 2, "value": "two"}]'
    path2.write_text(reordered)

    lb(["incremental-diff", "--join-keys=id", "--batch-size=1", str(path1), str(path2)])

    assert capsys.readouterr().out == ""


def test_id_driven_diff_reports_changed_and_added_rows(tmp_path, capsys):
    path1 = tmp_path / "one.jsonl"
    path2 = tmp_path / "two.jsonl"
    path1.write_text('{"id": 1, "value": "old"}\n{"id": 2, "value": "same"}\n')
    path2.write_text('{"id": 2, "value": "same"}\n{"id": 1, "value": "new"}\n{"id": 3, "value": "added"}\n')

    lb(["incremental-diff", "--join-keys=id", "--batch-size=1", str(path1), str(path2)])

    captured = capsys.readouterr().out
    assert "both" in captured
    assert "old" in captured
    assert "new" in captured
    assert "right_only" in captured
    assert "added" in captured


@pytest.mark.parametrize(
    ("left", "right", "message"),
    [
        ("id,value\n1,a\n1,b\n", "id,value\n1,a\n", "duplicate ID"),
        ("id,value\n,a\n", "id,value\n1,a\n", "missing ID value"),
        ("value\na\n", "value\na\n", "missing ID column"),
    ],
)
def test_id_driven_diff_rejects_invalid_ids(tmp_path, left, right, message):
    path1 = tmp_path / "one.csv"
    path2 = tmp_path / "two.csv"
    path1.write_text(left)
    path2.write_text(right)

    with pytest.raises(ValueError, match=message):
        lb(["incremental-diff", "--join-keys=id", str(path1), str(path2)])
