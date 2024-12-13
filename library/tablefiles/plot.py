import argparse, os, subprocess
from tempfile import NamedTemporaryFile

from library import usage
from library.utils import arggroups, argparse_utils, devices, file_utils, web
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
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args, unknown_args = parser.parse_known_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.table_like_post(args)
    arggroups.matplotlib_post(args, unknown_args)

    return args


def create_plot(args, df):
    # TODO: add --classify
    # df['category'] = df.col_name>0.5
    # df.groupby('category').count().plot(kind='bar', legend=False)

    plt = args.plot_fn(df)
    return plt


def file_plot(args, path):
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

        if getattr(args, "repl", False):
            breakpoint()

        if args.table_name == "stdin":
            print(f"## stdin:{df_name}")
        else:
            print(f"## {path}:{df_name}")

        plt = create_plot(args, df)

        if args.save:
            output_path = devices.clobber_new_file(args, f"{path}.{df_name}.png")
            log.debug("Saving to %s", output_path)
            plt.savefig(output_path)
            print("Saved to", output_path)

        if args.show_kitty:
            with NamedTemporaryFile(suffix=".png") as f:
                plt.savefig(f.name)
                subprocess.call(["kitty", "+kitten", "icat", f.name])

        if args.show_external:
            plt.show()


def plot():
    args = parse_args()

    web.requests_session(args)  # configure session
    for path in args.paths:
        file_plot(args, path)
