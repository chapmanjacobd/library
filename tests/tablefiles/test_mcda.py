import pytest

from xklb.lb import library as lb
from xklb.tablefiles import mcda
from xklb.utils.objects import NoneSpace
from xklb.utils.sql_utils import sort_like_sql

data = [
    {"name": "item 1", "duration": 30, "count": 5},
    {"name": "item 2", "duration": 20, "count": 10},
    {"name": "item 3", "duration": 20, "count": 7},
]


def test_sort_like_sql():
    result = sorted(data, key=sort_like_sql("count"))
    assert result == [
        {"name": "item 1", "duration": 30, "count": 5},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 2", "duration": 20, "count": 10},
    ]

    result = sorted(data, key=sort_like_sql("count desc"))
    assert result == [
        {"name": "item 2", "duration": 20, "count": 10},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 1", "duration": 30, "count": 5},
    ]

    result = sorted(data, key=sort_like_sql("name"))
    assert result == [
        {"name": "item 1", "duration": 30, "count": 5},
        {"name": "item 2", "duration": 20, "count": 10},
        {"name": "item 3", "duration": 20, "count": 7},
    ]

    result = sorted(data, key=sort_like_sql("name desc"))
    assert [
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 2", "duration": 20, "count": 10},
        {"name": "item 1", "duration": 30, "count": 5},
    ]

    result = sorted(data, key=sort_like_sql("duration, count"))
    assert result == [
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 2", "duration": 20, "count": 10},
        {"name": "item 1", "duration": 30, "count": 5},
    ]

    result = sorted(data, key=sort_like_sql("duration desc, count desc"))
    assert result == [
        {"name": "item 1", "duration": 30, "count": 5},
        {"name": "item 2", "duration": 20, "count": 10},
        {"name": "item 3", "duration": 20, "count": 7},
    ]

    result = mcda.group_sort_by(NoneSpace(sort_groups_by="mcda -duration,-count"), data)
    assert result == [
        {"name": "item 1", "duration": 30, "count": 5},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 2", "duration": 20, "count": 10},
    ]

    result = mcda.group_sort_by(NoneSpace(sort_groups_by="mcda duration,-count"), data)
    assert result == [
        {"name": "item 1", "duration": 30, "count": 5},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 2", "duration": 20, "count": 10},
    ]

    result = mcda.group_sort_by(NoneSpace(sort_groups_by="mcda duration,count"), data)
    assert result == [
        {"name": "item 2", "duration": 20, "count": 10},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 1", "duration": 30, "count": 5},
    ]


@pytest.mark.parametrize(
    "args,stdout",
    [
        (
            ["tests/data/test.xml"],
            """## tests/data/test.xml:0
### Shape

(2, 4)

### Goals

#### Maximize

- B
- C
- A
- index


|    |   index |   A |   B |   C |   TOPSIS |     MABAC |   SPOTIS |   BORDA |
|----|---------|-----|-----|-----|----------|-----------|----------|---------|
|  1 |       1 |   2 |   4 |   6 |        1 |  0.585786 |        0 | 4.41421 |
|  0 |       0 |   1 |   3 |   5 |        0 | -0.414214 |        1 | 5.41421 |

""",
        ),
    ],
)
def test_lb_mcda(args, stdout, capsys):
    lb(["mcda", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)
