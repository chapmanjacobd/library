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
