import sys

from xklb import usage
from xklb.utils import arggroups, argparse_utils, file_utils, web


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.markdown_tables)
    arggroups.table_like(parser)
    parser.add_argument("--sort", "-u", default="random()")
    arggroups.debug(parser)

    parser.add_argument(
        "paths",
        metavar="path",
        nargs="+",
        action=argparse_utils.ArgparseArgsOrStdin,
        help="path to one or more files",
    )
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.table_like_post(args)

    return args


def file_markdown(args, path):
    for df in file_utils.read_file_to_dataframes(
        path,
        table_name=args.table_name,
        table_index=args.table_index,
        start_row=args.start_row,
        end_row=args.end_row,
        order_by=args.sort,
        encoding=args.encoding,
        mimetype=args.mimetype,
        join_tables=args.join_tables,
    ):
        if getattr(args, "repl", False):
            breakpoint()
        if args.to_json:
            df.to_json(sys.stdout, orient="records", lines=True)
        else:
            print(f"## {path}:{df.name}")
            print()
            print(df.to_markdown(tablefmt="github", index=False))
            print()


def markdown_tables():
    args = parse_args()
    web.requests_session(args)  # configure session
    for path in args.paths:
        file_markdown(args, path)


if __name__ == "__main__":
    markdown_tables()
