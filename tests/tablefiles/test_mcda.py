import pytest
import pandas as pd

from library.__main__ import library as lb
from library.tablefiles import mcda
from library.utils.objects import NoneSpace
from library.utils.sql_utils import sort_like_sql

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
    ("args", "stdout"),
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


|    |   index |   A |   B |   C |   TOPSIS |     MABAC |   BORDA |
|----|---------|-----|-----|-----|----------|-----------|---------|
|  1 |       1 |   2 |   4 |   6 |        1 |  0.585786 | 4.41421 |
|  0 |       0 |   1 |   3 |   5 |        0 | -0.414214 | 5.41421 |

""",
        ),
    ],
)
def test_lb_mcda(args, stdout, capsys):
    lb(["mcda", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)


def test_mcda_end_row_checks_row_count(capsys):
    lb(["mcda", "--end-row", "4", "tests/data/test.xml"])

    assert "(limited by --end-row 4)" not in capsys.readouterr().out


def test_criterion_weights_accept_positional_and_named_values():
    alternatives = pd.DataFrame({"price": [1, 2], "quality": [2, 3]})

    assert mcda.criterion_weights(
        NoneSpace(weights=["1", "3"]), alternatives.columns, alternatives.to_numpy()
    ).tolist() == [0.25, 0.75]
    assert mcda.criterion_weights(
        NoneSpace(weights=["quality=3", "price=1"]), alternatives.columns, alternatives.to_numpy()
    ).tolist() == [0.25, 0.75]


@pytest.mark.parametrize(
    "weights",
    [
        ["1"],
        ["price=-1", "quality=1"],
        ["price=1", "other=1"],
        ["0", "0"],
    ],
)
def test_criterion_weights_validate_values(weights):
    alternatives = pd.DataFrame({"price": [1, 2], "quality": [2, 3]})

    with pytest.raises(ValueError):
        mcda.criterion_weights(NoneSpace(weights=weights), alternatives.columns, alternatives.to_numpy())


def test_categorical_conversion_uses_default_and_custom_mappings(tmp_path):
    args = NoneSpace(words_nums_map=None, nodata=0)
    frame = pd.DataFrame({"quality": ["low", "high"], "size": [1, 2]})
    converted = mcda.convert_categorical_columns(frame, args, ["quality"])
    assert converted["quality"].tolist() == [1.0, 5.0]

    mapping = tmp_path / "ratings.json"
    mapping.write_text('{"poor": 1, "excellent": 10}')
    args = NoneSpace(words_nums_map=str(mapping), nodata=0)
    frame = pd.DataFrame({"quality": ["poor", "excellent"]})
    converted = mcda.convert_categorical_columns(frame, args, ["quality"])
    assert converted["quality"].tolist() == [1.0, 10.0]


def test_pairwise_and_comet_rankings_are_available():
    alternatives = pd.DataFrame({"benefit": [1.0, 2.0, 3.0], "cost": [3.0, 2.0, 1.0]})
    args = NoneSpace(
        weights=["0.8", "0.2"],
        mcda_method=None,
        pairwise=True,
        comet=True,
        nodata=0,
    )

    ranked = mcda.auto_mcda(args, alternatives, minimize_cols={"cost"})
    assert {"PAIRWISE", "COMET", "BORDA"} <= set(ranked.columns)
    assert ranked["original_index"].tolist() == [2, 1, 0]


def test_pca_diagnostics_report_feature_contributions():
    diagnostics = mcda.pca_diagnostics(
        pd.DataFrame({"a": [0.0, 1.0, 2.0], "b": [0.0, 1.0, 2.0], "c": [1.0, 1.0, 1.0]})
    )

    assert set(diagnostics.columns) == {"criterion", "variance_fraction", "variance_percent"}
    assert diagnostics["variance_fraction"].sum() == pytest.approx(1)
    assert diagnostics.loc[diagnostics["criterion"] == "c", "variance_fraction"].item() == pytest.approx(0)
