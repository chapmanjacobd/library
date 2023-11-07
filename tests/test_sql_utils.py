from types import SimpleNamespace

from xklb.scripts import mcda
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

    result = mcda.group_sort_by(SimpleNamespace(sort_by="mcda -duration,-count"), data)
    assert result == [
        {"name": "item 1", "duration": 30, "count": 5},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 2", "duration": 20, "count": 10},
    ]

    result = mcda.group_sort_by(SimpleNamespace(sort_by="mcda duration,-count"), data)
    assert result == [
        {"name": "item 1", "duration": 30, "count": 5},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 2", "duration": 20, "count": 10},
    ]

    result = mcda.group_sort_by(SimpleNamespace(sort_by="mcda duration,count"), data)
    assert result == [
        {"name": "item 2", "duration": 20, "count": 10},
        {"name": "item 3", "duration": 20, "count": 7},
        {"name": "item 1", "duration": 30, "count": 5},
    ]
