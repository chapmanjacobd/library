import argparse, os, re, subprocess, sys
from tempfile import NamedTemporaryFile

from library import usage
from library.utils import arggroups, argparse_utils, devices, file_utils, processes, web
from library.utils.log_utils import log

IS_KITTY = os.getenv("TERM") == "xterm-kitty"


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.plot)
    parser.add_argument("--save", action="store_true", help="Save plots to PNG")
    parser.add_argument(
        "--show-kitty", default=IS_KITTY, action=argparse.BooleanOptionalAction, help="Show plots inline"
    )
    parser.add_argument(
        "--show-external",
        action=argparse.BooleanOptionalAction,
        default=not IS_KITTY,
        help="Show plots in external window",
    )
    arggroups.table_like(parser)
    parser.add_argument("--sort", "-u", default="random()")

    transform = parser.add_argument_group("Transform")
    transform.add_argument(
        "--where",
        "-w",
        action="append",
        default=[],
        metavar="EXPR",
        help="""Filter rows with a pandas expression. Repeatable; all conditions are AND-ed.
-w 'duration > 60'
-w 'size < 1GB and category != \"audio\"'""",
    )
    transform.add_argument(
        "--classify",
        "-c",
        metavar="EXPR",
        help="""Derive a `category` column. Either a pandas expression or an existing column name.
-c 'size > 1GB'
-c size --bins 5
-c size --quantiles 4""",
    )
    transform.add_argument("--bins", type=int, help="Split a numeric --classify column into this many equal-width bins")
    transform.add_argument(
        "--quantiles", type=int, help="Split a numeric --classify column into this many quantile bins"
    )
    transform.add_argument(
        "--groupby", "-g", metavar="COL", help="Group rows by a column (e.g. the derived `category`) and aggregate"
    )
    transform.add_argument(
        "--agg",
        default="count",
        choices=["count", "sum", "mean", "median", "min", "max"],
        help="Aggregate function used with --groupby (default: count)",
    )
    transform.add_argument(
        "--top", type=int, help="Keep only the N most numerous groups when using --groupby"
    )
    transform.add_argument(
        "--scale",
        default="auto",
        choices=["auto", "log", "symlog", "logit", "off"],
        help="""Detect a fitting axis scale for each numeric column and render it accordingly.
`auto` picks linear for normal data, log for log-normal or heavy right-skewed positive data,
symlog for data spanning orders of magnitude that includes zero/negative values, and logit for
proportions in (0,1); a fitted PDF is overlaid when a normal/lognormal match is found.
Forcing a value applies that scale to all histograms; `off` draws plain linear histograms.""",
    )

    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)

    # Everything after `--` is treated as a matplotlib command instead of a file path.
    # e.g. lb plot data.csv -- scatter x y s=3 alpha=0.5
    argv = sys.argv[1:]
    plot_args = []
    if "--" in argv:
        separator = argv.index("--")
        plot_args = argv[separator + 1 :]
        argv = argv[:separator]

    args, unknown_args = parser.parse_known_intermixed_args(argv)
    arggroups.args_post(args, parser)

    arggroups.table_like_post(args)
    arggroups.matplotlib_post(args, [*plot_args, *unknown_args])

    return args


def create_plot(args, df):
    plots = args.plot_fn(df)
    if isinstance(plots, list):
        return plots
    return [plots]


def figure_stem(plot):
    """Return a short slug from a figure's title, used to name saved files."""
    try:
        ax = plot.axes[0]
    except (AttributeError, IndexError, TypeError):
        return "plot"
    title = ax.get_title()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "plot"


BYTE_UNITS = {
    "b": 2**0,
    "kb": 2**10,
    "mb": 2**20,
    "gb": 2**30,
    "tb": 2**40,
    "pb": 2**50,
    "k": 2**10,
    "g": 2**30,
    "t": 2**40,
    "p": 2**50,
}
DURATION_UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
    "mo": 2592000,
    "mon": 2592000,
    "month": 2592000,
    "months": 2592000,
    "y": 31536000,
    "yr": 31536000,
    "yrs": 31536000,
    "year": 31536000,
    "years": 31536000,
}


def humanize_units(expr):
    """Rewrite human units (1GB, 90s, 2min) in a pandas expression to raw numbers."""

    def repl(m):
        unit = m.group(2).lower()
        if unit in BYTE_UNITS:
            return str(int(float(m.group(1)) * BYTE_UNITS[unit]))
        if unit in DURATION_UNITS:
            return str(int(float(m.group(1)) * DURATION_UNITS[unit]))
        return m.group(0)

    return re.sub(r"(\d+\.?\d*)\s*([a-zA-Z]+)", repl, expr)


def convert_human_columns(df):
    """Convert object columns of human values (2GB, 90s, 2min) to numbers."""
    import pandas as pd

    for col in df.columns:
        if not pd.api.types.is_object_dtype(df[col]):
            continue
        vals = df[col].dropna()
        if vals.empty:
            continue
        cleaned = vals.astype(str).str.strip()
        if not cleaned.str.match(r"^\d+(?:\.\d+)?[a-zA-Z]+$").all():
            continue
        units = set(cleaned.str.extract(r"([a-zA-Z]+)$")[0].str.lower())
        if units <= set(BYTE_UNITS):
            table = BYTE_UNITS
        elif units <= set(DURATION_UNITS):
            table = DURATION_UNITS
        else:
            continue

        numbers = cleaned.str.extract(r"(\d+(?:\.\d+)?)")[0].astype(float)
        letters = cleaned.str.extract(r"([a-zA-Z]+)$")[0].str.lower()
        converted = pd.Series(float("nan"), index=df.index)
        converted.loc[vals.index] = (numbers * letters.map(table)).astype("int64")
        df[col] = converted


def classify_column(df, arg, bins, quantiles):
    import pandas as pd

    if arg in df.columns:
        s = pd.to_numeric(df[arg], errors="coerce") if (bins or quantiles) else df[arg]
        if bins:
            return pd.cut(s, bins=bins)
        if quantiles:
            return pd.qcut(s, q=quantiles, duplicates="drop")
        return s
    return df.eval(humanize_units(arg))


def groupby_df(df, col, agg, top):
    if col not in df.columns:
        processes.exit_error(f"--groupby column {col!r} not found in {list(df.columns)}")

    sizes = df.groupby(col, dropna=False, observed=True).size().rename("count")
    if top:
        sizes = sizes.nlargest(top)

    if agg == "count":
        grouped = sizes.reset_index()
    else:
        numeric_cols = df.select_dtypes("number").columns
        if numeric_cols.empty:
            grouped = sizes.reset_index()
        else:
            grouped = df.groupby(col, dropna=False, observed=True)[numeric_cols].agg(agg)
            grouped = grouped.reindex(sizes.index).reset_index()

    grouped.attrs["plot_grouped"] = True
    grouped.attrs["plot_agg"] = agg
    return grouped


def transform_df(args, df):
    convert_human_columns(df)

    for w in args.where:
        df = df.query(humanize_units(w))

    if args.classify:
        df = df.copy()
        df["category"] = classify_column(df, args.classify, args.bins, args.quantiles)

    if args.groupby:
        df = groupby_df(df, args.groupby, args.agg, args.top)

    return df


def file_plot(args, path):
    import matplotlib.pyplot as plt

    plt.rcParams["figure.max_open_warning"] = 100  # auto mode can open many figures

    for df_name, df in file_utils.read_file_to_dataframes(
        path,
        table_name=args.table_name,
        table_index=args.table_index,
        start_row=args.start_row,
        end_row=args.end_row,
        order_by=args.sort,
        encoding=args.encoding,
        mimetype=args.mimetype,
        join_tables=args.join_tables,
        transpose=args.transpose,
        skip_headers=args.skip_headers,
    ):
        if args.cols:
            df = df[args.cols]

        df = transform_df(args, df)

        if getattr(args, "repl", False):
            breakpoint()

        if args.table_name == "stdin":
            print(f"## stdin:{df_name}")
        else:
            print(f"## {path}:{df_name}")

        plt.close("all")  # start each dataset on a fresh set of figures
        figures = create_plot(args, df)

        for plot in figures:
            if args.save:
                if len(figures) > 1:
                    output_path = devices.clobber_new_file(args, f"{path}.{df_name}.{figure_stem(plot)}.png")
                else:
                    output_path = devices.clobber_new_file(args, f"{path}.{df_name}.png")
                log.debug("Saving to %s", output_path)
                plot.savefig(output_path)
                print("Saved to", output_path)

            if args.show_kitty:
                with NamedTemporaryFile(suffix=".png") as f:
                    plot.savefig(f.name)
                    subprocess.call(["kitty", "+kitten", "icat", f.name])

        if args.show_external:
            plt.show()


def plot():
    args = parse_args()

    web.requests_session(args)  # configure session
    for path in args.paths:
        file_plot(args, path)
