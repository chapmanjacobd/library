import sys

from xklb import usage
from xklb.playback import media_printer
from xklb.utils import arggroups, argparse_utils, file_utils, web


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.columns)
    arggroups.table_like(parser)
    parser.add_argument("--sort", "-u", default="random()")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    if "end_row" in args.defaults:
        args.end_row = str(args.start_row + 1) if args.start_row is not None else "2"
    arggroups.table_like_post(args)

    return args


def file_columns(args, path):
    import pandas as pd

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
        if (df.dtypes == "object").all():
            df = df.convert_dtypes()
        dc = [(col, df.dtypes[col]) for col in df.columns]
        df = pd.DataFrame(dc, columns=["name", "type"])

        if args.cols:
            df = df[args.cols]

        if args.to_json:
            df.to_json(sys.stdout, orient="records", lines=True)
        elif len(df.columns) == 1:
            series = df.iloc[:, 0]
            for value in series:
                print(value)
        elif args.print:
            media_printer.media_printer(args, df.to_dict(orient="records"))
        else:
            print(f"## {path}:{df_name}")
            print()
            print(df.to_markdown(tablefmt="github", index=False))
            print()


def columns():
    args = parse_args()
    web.requests_session(args)  # configure session
    for path in args.paths:
        file_columns(args, path)


if __name__ == "__main__":
    columns()
