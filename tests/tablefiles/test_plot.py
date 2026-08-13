import matplotlib.pyplot as plt
import pytest

from library.__main__ import library as lb


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
