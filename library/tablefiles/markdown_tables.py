import sys

from library.playback import media_printer
from library.utils import arggroups, argparse_utils, file_utils, printing, web
from library.utils.log_utils import check_stdio

USAGE = {
    'markdown_tables': """library table markdown PATH ... [--table STR] [--end-row INT] [--transpose] [--filetype]

    Print tables from files as markdown

    Only 500,000 rows per file are loaded for performance purposes. Set `--end-row inf` to read all the rows and/or run out of RAM.

    Examples:

    lb database search cities.db places chic | lb table --from-json --transpose

    ## stdin:0

    | 0                       | 1          | 2                        | 3                        | 4                        | 5          |
    |-------------------------|------------|--------------------------|--------------------------|--------------------------|------------|
    | title                   | Chiclayo   | Chicago                  | Chico                    | Apalachicola             | Chicoutimi |
    | state                   | Lambayeque | Illinois                 | California               | Florida                  | Québec     |
    | country                 | Peru       | United States of America | United States of America | United States of America | Canada     |
    | u                       | PE         | US                       | US                       | US                       | CA         |
    | latitude                | -6.7629    | 41.8319                  | 39.7286                  | 29.7256                  | 48.4333    |
    | longitude               | -79.8366   | -87.752                  | -121.8364                | -84.9925                 | -71.0667   |
    | size                    | 22184      | 19571                    | 40437                    | 35467                    | 28951      |
    | interesting_avg         | 141        | 1129                     | 156                      | 119                      | 175        |
    | interesting_spread      | 1754       | 26919                    | 2025                     | 1297                     | 3196       |
    | boring_avg              | 349        | 4332                     | 136                      | 382                      | 628        |
    | boring_spread           | 4186       | 24220                    | 2000                     | 2432                     | 3920       |
    | pop_avg                 | 7530       | 12906                    | 1350                     | 378                      | 3038       |
    | pop_spread              | 80471      | 80825                    | 24196                    | 1634                     | 15249      |
    | food_avg                | 28         | 18                       | 8                        | 7                        | 8          |
    | food_spread             | 153        | 417                      | 51                       | 27                       | 26         |
    | urban_avg               | 60         | 38                       | 11                       | 2                        | 22         |
    | urban_spread            | 80         | 99                       | 45                       | 2                        | 71         |
    | forest_avg              | 11         | 55                       | 82                       | 77                       | 72         |
    | forest_spread           | 27         | 155                      | 264                      | 186                      | 203        |
    | aqi_avg                 | 9          | 11                       | 5                        | 7                        | 2          |
    | aqi_max                 | 23         | 14                       | 11                       | 9                        | 6          |
    | coastline_avg           | 0          | 0                        | 0                        | 23                       | 26         |
    | slope_avg               | 1542       | 420                      | 3532                     | 248                      | 2071       |
    | public_transport_avg    | 8          | 34                       | 1                        | 1                        | 2          |
    | public_transport_spread | 24         | 303                      | 9                        | 1                        | 7          |
    | hotel_count             | 56         | 259                      | 75                       | 2561                     |            |
    | airport_code            | CIX,LOH    | CMI,MDW,MKG              | RDD,SMF                  | ECP,TLH                  | YBG        |
    | wifi                    | 37505      | 177564                   | 171754                   | 195347                   | 150669     |
""",
}


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=USAGE['markdown_tables'])
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
