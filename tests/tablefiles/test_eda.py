import pytest

from xklb.lb import library as lb


@pytest.mark.parametrize(
    "args,stdout",
    [
        (
            ["tests/data/test.xml"],
            """## tests/data/test.xml:0
### Shape

(2, 4)

### Sample of rows

|    |   index |   A |   B |   C |
|----|---------|-----|-----|-----|
|  0 |       0 |   1 |   3 |   5 |
|  1 |       1 |   2 |   4 |   6 |

### Summary statistics

|       |    index |        A |        B |        C |
|-------|----------|----------|----------|----------|
| count | 2        | 2        | 2        | 2        |
| mean  | 0.5      | 1.5      | 3.5      | 5.5      |
| std   | 0.707107 | 0.707107 | 0.707107 | 0.707107 |
| min   | 0        | 1        | 3        | 5        |
| 25%   | 0.25     | 1.25     | 3.25     | 5.25     |
| 50%   | 0.5      | 1.5      | 3.5      | 5.5      |
| 75%   | 0.75     | 1.75     | 3.75     | 5.75     |
| max   | 1        | 2        | 4        | 6        |

### Pandas columns with 'converted' dtypes

| column   | original_dtype   | converted_dtype   |
|----------|------------------|-------------------|
| index    | int64            | Int64             |
| A        | int64            | Int64             |
| B        | int64            | Int64             |
| C        | int64            | Int64             |

### Missing values

0 nulls/NaNs (0.0% dataset values missing)
""",
        ),
    ],
)
def test_lb_eda(args, stdout, capsys):
    lb(["eda", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)
