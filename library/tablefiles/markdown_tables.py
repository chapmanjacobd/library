import sys

from library import usage
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, file_utils, printing, web
from library.utils.log_utils import check_stdio


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.markdown_tables)
    arggroups.table_like(parser)
    parser.add_argument("--sort", "-u", default="random()")
    parser.add_argument("--to-parquet", action="store_true", help="Write to Parquet")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.table_like_post(args)

    return args


def file_markdown(args, path):
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
        if args.to_json:
            df.to_json(sys.stdout, orient="records", lines=True)
        elif args.to_parquet:
            _has_stdin, has_stdout = check_stdio()
            if has_stdout:
                output_path = (args.table_name or df_name) + ".parquet"
                df.to_parquet(output_path, index=None, compression="zstd")
            else:
                sys.stdout.buffer.write(df.to_parquet(index=None, compression="zstd"))
        elif args.print:
            media_printer.media_printer(args, df.to_dict(orient="records"))
        else:
            if args.table_name == "stdin":
                print(f"## stdin:{df_name}")
            else:
                print(f"## {path}:{df_name}")
            print()
            printing.table(df.to_dict(orient="records"))
            print()


def markdown_tables():
    args = parse_args()
    web.requests_session(args)  # configure session
    for path in args.paths:
        file_markdown(args, path)
