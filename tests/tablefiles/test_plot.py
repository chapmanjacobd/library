import matplotlib.pyplot as plt
import pytest

from library.__main__ import library as lb


def _figure_by_title(title):
    for num in plt.get_fignums():
        for ax in plt.figure(num).axes:
            if ax.get_title() == title:
                return ax
    raise AssertionError(f"no figure titled {title!r}")


@pytest.mark.parametrize(
    ("args", "stdout"),
    [
        (
            ["--no-show-kitty", "--no-show-external", "tests/data/test.xml"],
            """## tests/data/test.xml:0

""",
        ),
        (
            [
                "--no-show-kitty",
                "--no-show-external",
                "tests/data/test.xml",
                "--",
                "plot",
                "A",
                "B",
            ],
            """## tests/data/test.xml:0

""",
        ),
        (
            [
                "--no-show-kitty",
                "--no-show-external",
                "tests/data/test.xml",
                "--",
                "scatter",
                "A",
                "B",
                "s=3",
                "alpha=0.5",
            ],
            """## tests/data/test.xml:0

""",
        ),
        (
            [
                "--no-show-kitty",
                "--no-show-external",
                "tests/data/test.xml",
                "--",
                "hist",
                "A",
                "bins=5",
            ],
            """## tests/data/test.xml:0

""",
        ),
        (
            [
                "--no-show-kitty",
                "--no-show-external",
                "tests/data/test.xml",
                "--",
                "plot",
                "A",
            ],
            """## tests/data/test.xml:0

""",
        ),
        (
            [
                "--no-show-kitty",
                "--no-show-external",
                "tests/data/test.xml",
                "--",
                "plot",
                "A",
                "B",
                "xlabel=test",
                "grid=True",
            ],
            """## tests/data/test.xml:0

""",
        ),
        (
            [
                "--no-show-kitty",
                "--no-show-external",
                "tests/data/test.xml",
                "--cols",
                "A,B",
                "--",
                "plot",
                "index",
                "A",
            ],
            """## tests/data/test.xml:0

""",
        ),
    ],
)
def test_lb_plot(args, stdout, capsys):
    lb(["plot", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)


def test_lb_plot_auto_labels():
    plt.close("all")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "tests/data/test.xml",
            "--",
            "scatter",
            "A",
            "B",
        ]
    )
    ax = plt.gca()
    assert ax.get_xlabel() == "A"
    assert ax.get_ylabel() == "B"


def test_lb_plot_units_formatter(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("size,duration\n1000,10\n2000000,30\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--",
            "scatter",
            "size",
            "duration",
        ]
    )
    from matplotlib.ticker import FuncFormatter

    ax = plt.gca()
    assert ax.get_xlabel() == "Size (bytes)"
    assert isinstance(ax.xaxis.get_major_formatter(), FuncFormatter)
    assert ax.get_ylabel() == "Duration (s)"
    assert isinstance(ax.yaxis.get_major_formatter(), FuncFormatter)


def test_lb_plot_explicit_label_wins():
    plt.close("all")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "tests/data/test.xml",
            "--",
            "scatter",
            "A",
            "B",
            "xlabel=Custom",
        ]
    )
    ax = plt.gca()
    assert ax.get_xlabel() == "Custom"
    assert ax.get_ylabel() == "B"


def test_lb_plot_auto_title():
    plt.close("all")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "tests/data/test.xml",
            "--",
            "scatter",
            "A",
            "B",
        ]
    )
    assert plt.gca().get_title() == "B vs A"


def test_lb_plot_auto_title_hist():
    plt.close("all")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "tests/data/test.xml",
            "--",
            "hist",
            "A",
            "bins=5",
        ]
    )
    assert plt.gca().get_title() == "A Distribution"


def test_lb_plot_explicit_title_wins():
    plt.close("all")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "tests/data/test.xml",
            "--",
            "scatter",
            "A",
            "B",
            "title=Custom Title",
        ]
    )
    assert plt.gca().get_title() == "Custom Title"


def test_lb_plot_hist_counts(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("duration\n1\n2\n3\n4\n5\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--",
            "hist",
            "duration",
            "bins=3",
        ]
    )
    ax = plt.gca()
    assert ax.get_xlabel() == "Duration (s)"
    assert ax.get_ylabel() == "Count"


def test_lb_plot_auto_mode_generates_multiple_figures(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text(
        "category,size,duration,time_created\n"
        "a,100,10,1600000000\n"
        "b,200,20,1600001000\n"
        "a,300,30,1600002000\n"
        "b,400,15,1600003000\n"
        "c,500,25,1600004000\n"
    )
    lb(["plot", "--no-show-kitty", "--no-show-external", str(df)])
    titles = [ax.get_title() for num in plt.get_fignums() for ax in plt.figure(num).axes]

    assert len(plt.get_fignums()) >= 6
    assert "Size Distribution" in titles
    assert "Duration Distribution" in titles
    assert "Common Values of Category" in titles
    assert "Duration over time" in titles
    assert "Correlation Heatmap" in titles
    assert "Time Created vs Size" in titles


def test_lb_plot_auto_mode_skips_key_columns(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("id,category\n1,a\n2,a\n3,b\n4,b\n")
    lb(["plot", "--no-show-kitty", "--no-show-external", str(df)])
    titles = [ax.get_title() for num in plt.get_fignums() for ax in plt.figure(num).axes]

    assert titles == ["Common Values of Category"]


def test_lb_plot_auto_mode_save(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("a,b\n1,2\n2,4\n3,6\n")
    lb(["plot", "--no-show-kitty", "--no-show-external", "--save", str(df)])
    saved = [p for p in tmp_path.iterdir() if p.suffix == ".png"]
    assert saved
    assert any("distribution" in p.name for p in saved)


def test_lb_plot_explicit_mode_overrides_auto(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("a,b\n1,2\n2,4\n3,6\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--",
            "scatter",
            "a",
            "b",
        ]
    )
    assert len(plt.get_fignums()) == 1
    assert plt.gca().get_title() == "B vs A"


def test_lb_plot_fresh_figure_per_file(tmp_path):
    plt.close("all")
    f1 = tmp_path / "f1.csv"
    f2 = tmp_path / "f2.csv"
    f1.write_text("x,y\n1,1\n2,2\n")
    f2.write_text("x,y\n3,9\n4,16\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(f1),
            str(f2),
            "--",
            "scatter",
            "x",
            "y",
        ]
    )
    assert len(plt.gcf().axes[0].collections) == 1


def test_lb_plot_separator_between_commands(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("a,b\n1,10\n2,20\n3,30\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--",
            "hist",
            "a",
            "bins=2",
            "--",
            "hist",
            "b",
            "bins=2",
        ]
    )
    assert len(plt.gcf().axes[0].patches) == 4  # 2 histograms x 2 bins
    assert plt.gca().get_ylabel() == "Count"


def test_lb_plot_where_filters_rows(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("size,duration\n100,10\n500,30\n2048,60\n1024,20\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--where",
            "size > 1000",
            "--",
            "plot",
            "duration",
        ]
    )
    assert plt.gca().get_ylabel() == "Duration (s)"
    line = plt.gca().lines[0]
    assert len(line.get_ydata()) == 2  # only 60 and 20 remain


def test_lb_plot_classify_expression(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("size,duration\n100,10\n500,30\n2048,60\n1024,20\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--classify",
            "size > 1000",
            "--groupby",
            "category",
        ]
    )
    ax = plt.gca()
    assert ax.get_title() == "Count per Category"
    assert len(ax.patches) == 2  # one bar per group (True/False)


def test_lb_plot_classify_bins(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("size,duration\n100,10\n500,30\n2048,60\n1024,20\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--classify",
            "size",
            "--bins",
            "2",
            "--groupby",
            "category",
            "--agg",
            "mean",
        ]
    )
    ax = _figure_by_title("Mean Size per Category")
    assert len(ax.patches) == 2  # two bins


def test_lb_plot_groupby_count_and_top(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("category,size\nc,100\nb,200\na,300\na,400\nb,500\nb,600\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--groupby",
            "category",
            "--top",
            "2",
        ]
    )
    ax = plt.gca()
    assert ax.get_title() == "Count per Category"
    assert len(ax.patches) == 2  # b (3) and a (2); c dropped


def test_lb_plot_groupby_mean(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("category,size,duration\na,100,10\na,300,30\nb,50,5\nb,150,15\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--groupby",
            "category",
            "--agg",
            "mean",
        ]
    )
    ax = _figure_by_title("Mean Size per Category")
    sizes = [p.get_height() for p in ax.patches]
    assert sorted(sizes) == [100.0, 200.0]  # mean size of a and b


def test_lb_plot_human_units(tmp_path):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("size,duration\n2GB,90s\n1GB,2min\n500MB,5s\n")
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--classify",
            "size > 1GB",
            "--groupby",
            "category",
        ]
    )
    ax = plt.gca()
    assert ax.get_title() == "Count per Category"
    assert len(ax.patches) == 2  # True (2GB) and False (1GB, 500MB)


def test_lb_plot_groupby_missing_column(tmp_path, caplog):
    plt.close("all")
    df = tmp_path / "data.csv"
    df.write_text("size,duration\n100,10\n200,20\n")
    with pytest.raises(SystemExit):
        lb(
            [
                "plot",
                "--no-show-kitty",
                "--no-show-external",
                str(df),
                "--groupby",
                "nope",
            ]
        )
    assert "--groupby column 'nope' not found" in caplog.text


def _write_lognormal(tmp_path, seed=7):
    import numpy as np

    df = tmp_path / "data.csv"
    rng = np.random.default_rng(seed)
    df.write_text("size\n" + "\n".join(map(str, rng.lognormal(3, 1.2, 500))) + "\n")
    return df


def _write_normal(tmp_path, seed=7):
    import numpy as np

    df = tmp_path / "data.csv"
    rng = np.random.default_rng(seed)
    df.write_text("a\n" + "\n".join(map(str, rng.normal(50, 10, 500))) + "\n")
    return df


def test_lb_plot_auto_detects_lognormal(tmp_path):
    plt.close("all")
    df = _write_lognormal(tmp_path)
    lb(["plot", "--no-show-kitty", "--no-show-external", str(df)])
    ax = _figure_by_title("Size Distribution (Log-normal)")
    assert ax.get_xscale() == "log"
    assert len(ax.lines) == 1  # fitted lognormal PDF overlay


def test_lb_plot_auto_overlays_pdf_for_normal(tmp_path):
    plt.close("all")
    df = _write_normal(tmp_path)
    lb(["plot", "--no-show-kitty", "--no-show-external", str(df)])
    ax = _figure_by_title("A Distribution")
    assert ax.get_xscale() == "linear"
    assert len(ax.lines) == 1  # fitted normal PDF overlay


def test_lb_plot_scale_off_disables_detection(tmp_path):
    plt.close("all")
    df = _write_lognormal(tmp_path)
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "--scale",
            "off",
            str(df),
        ]
    )
    ax = _figure_by_title("Size Distribution")
    assert ax.get_xscale() == "linear"
    assert len(ax.lines) == 0


def test_lb_plot_scale_log_forces_log_scale(tmp_path):
    plt.close("all")
    df = _write_normal(tmp_path)
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "--scale",
            "log",
            str(df),
        ]
    )
    ax = _figure_by_title("A Distribution (Log)")
    assert ax.get_xscale() == "log"


def test_lb_plot_manual_hist_detects_lognormal(tmp_path):
    plt.close("all")
    df = _write_lognormal(tmp_path)
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            str(df),
            "--",
            "hist",
            "size",
        ]
    )
    ax = plt.gca()
    assert ax.get_xscale() == "log"
    assert len(ax.lines) == 1


def test_lb_plot_manual_hist_forced_log(tmp_path):
    plt.close("all")
    df = _write_normal(tmp_path)
    lb(
        [
            "plot",
            "--no-show-kitty",
            "--no-show-external",
            "--scale",
            "log",
            str(df),
            "--",
            "hist",
            "a",
        ]
    )
    ax = plt.gca()
    assert ax.get_xscale() == "log"


def test_detect_distribution():
    import numpy as np
    import pandas as pd

    from library.utils.arggroups import detect_distribution

    rng = np.random.default_rng(3)
    assert detect_distribution(pd.Series(rng.normal(50, 10, 500))) == "normal"
    assert detect_distribution(pd.Series(rng.lognormal(3, 1, 500))) == "lognormal"
    assert detect_distribution(pd.Series(rng.exponential(50, 500))) == "log"
    assert detect_distribution(pd.Series(rng.beta(0.5, 0.5, 500))) == "logit"
    assert detect_distribution(pd.Series(rng.gamma(5, 1, 500))) == "skewed"
    assert detect_distribution(pd.Series([1, 2, 3])) is None  # too few samples
    assert detect_distribution(pd.Series([0, 1, 2, 3])) in (None, "skewed")  # non-positive can't be lognormal
