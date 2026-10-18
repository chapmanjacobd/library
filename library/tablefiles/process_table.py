import argparse, os, sys
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, devices, file_utils
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_table)
    arggroups.table_like(parser)
    parser.add_argument("--output-path", "-o", help="Output Parquet file (only valid for one table)")
    parser.add_argument("--compression", choices=["brotli", "gzip", "lz4", "snappy", "zstd"], default="zstd")
    parser.add_argument("--delete-original", action="store_true", help="Delete source tables after conversion")
    arggroups.clobber(parser)
    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    arggroups.table_like_post(args)
    return args


def _output_path(args, source: str, table_name: str | None, table_count: int) -> Path:
    if args.output_path:
        if table_count != 1:
            raise SystemExit("--output-path requires exactly one input table")
        return Path(args.output_path)

    source_path = Path(source)
    if table_name and table_count > 1:
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(table_name))
        return source_path.with_name(f"{source_path.stem}.{safe_name}.parquet")
    return source_path.with_suffix(".parquet")


def process_path(args, path: str) -> list[str]:
    dfs = file_utils.read_file_to_dataframes(
        path,
        table_name=args.table_name,
        table_index=args.table_index,
        start_row=args.start_row,
        end_row=args.end_row,
        encoding=args.encoding,
        mimetype=args.mimetype,
        join_tables=args.join_tables,
        transpose=args.transpose,
        skip_headers=args.skip_headers,
    )
    outputs = []
    for table_name, df in dfs:
        output_path = _output_path(args, path, table_name, len(dfs))
        output_path = Path(devices.clobber_new_file(args, str(output_path)))
        try:
            df.to_parquet(output_path, index=False, compression=args.compression)
        except ImportError:
            print(
                "Parquet output requires pandas and either pyarrow or fastparquet",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        outputs.append(str(output_path))
        log.info("Saved %s", output_path)

    if args.delete_original and path != "-":
        Path(path).unlink()
    return outputs


def process_table() -> None:
    args = parse_args()
    for path in args.paths:
        process_path(args, path)
