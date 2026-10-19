import argparse
import csv
import io
import json
import sys
from collections import OrderedDict
from contextlib import nullcontext
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils


def _parser(usage_text: str) -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=usage_text)
    arggroups.debug(parser)
    return parser


def _input_context(path: str | None):
    if not path or path == "-":
        return nullcontext(sys.stdin)
    return Path(path).open(newline="", encoding="utf-8")


def _read_json(path: str | None):
    with _input_context(path) as fd:
        text = fd.read()
    try:
        return json.loads(text, object_pairs_hook=OrderedDict)
    except json.JSONDecodeError as initial:
        try:
            return [
                json.loads(line, object_pairs_hook=OrderedDict)
                for line in text.splitlines()
                if line.strip()
            ]
        except json.JSONDecodeError:
            raise initial from None


def _rows_from_json(data) -> list[dict]:
    if isinstance(data, list) and all(isinstance(item, dict) for item in data):
        return data
    if isinstance(data, list) and all(isinstance(item, list) for item in data):
        if not data:
            return []
        columns = [str(column) for column in data[0]]
        return [dict(zip(columns, row, strict=False)) for row in data[1:]]
    if isinstance(data, dict) and all(isinstance(value, list) for value in data.values()):
        length = max((len(value) for value in data.values()), default=0)
        return [
            OrderedDict((key, values[index] if index < len(values) else None) for key, values in data.items())
            for index in range(length)
        ]
    raise ValueError("input must be a JSON list of dictionaries or a dictionary with lists")


def parse_json_to_csv_args() -> argparse.Namespace:
    parser = _parser(usage.json_to_csv)
    parser.add_argument("-f", "--file", dest="input_path", help="JSON file (default: stdin)")
    parser.add_argument("-s", "--separator", "--delimiter", default=",")
    parser.add_argument("-k", "--keep-only", action="store_true")
    parser.add_argument("fields", nargs="*")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def json_to_csv() -> None:
    args = parse_json_to_csv_args()
    rows = _rows_from_json(_read_json(args.input_path))
    requested = args.fields
    keys = list(dict.fromkeys(requested))
    if not args.keep_only:
        keys.extend(key for row in rows for key in row if key not in keys)

    writer = csv.DictWriter(sys.stdout, fieldnames=keys, delimiter=args.separator)
    writer.writeheader()
    writer.writerows({key: row.get(key) for key in keys} for row in rows)


def _split_columns(columns: str | None) -> list[str] | None:
    if not columns:
        return None
    return [column.strip() for column in columns.split(",")]


def parse_csv_to_json_args() -> argparse.Namespace:
    parser = _parser(usage.csv_to_json)
    parser.add_argument("input_path", nargs="?", default="-")
    parser.add_argument("--column-names", help="Comma-separated column names for headerless input")
    parser.add_argument("--header", action="store_true", help="Treat the first row as column names")
    parser.add_argument("-d", "--delimiter", default=",")
    parser.add_argument("--sniff", action="store_true", help="Detect the CSV dialect and header")
    parser.add_argument("--indent", type=int)
    args = parser.parse_args()
    if args.header and args.column_names:
        parser.error("--header and --column-names cannot be used together")
    arggroups.args_post(args, parser)
    return args


def csv_to_json() -> None:
    args = parse_csv_to_json_args()
    with _input_context(args.input_path) as fd:
        text = fd.read()
        sample = text[:4096]
        input_stream = io.StringIO(text)
        dialect = csv.Sniffer().sniff(sample) if args.sniff and sample else None
        delimiter = dialect.delimiter if dialect else args.delimiter
        use_header = args.header or (bool(dialect) and not args.column_names and csv.Sniffer().has_header(sample))
        if use_header:
            rows = list(csv.DictReader(input_stream, delimiter=delimiter))
        else:
            rows = [
                OrderedDict((str(index), value) for index, value in enumerate(row))
                for row in csv.reader(input_stream, delimiter=delimiter)
            ]

    if args.column_names and not use_header:
        columns = _split_columns(args.column_names) or []
        rows = [
            OrderedDict((column, row.get(str(index))) for index, column in enumerate(columns))
            for row in rows
        ]
    json.dump(rows, sys.stdout, indent=args.indent)
    sys.stdout.write("\n")
