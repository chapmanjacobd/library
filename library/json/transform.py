import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from library.utils import arggroups, argparse_utils

USAGE = {
    "remove_nulls": """library json remove-nulls [PATH] [--indent N]

    Remove null values recursively from JSON objects and arrays.
    --indent is only supported for a single JSON document, not JSONL input.
""",
}


def _parser(usage: str) -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.debug(parser)
    parser.add_argument("path", nargs="?")
    return parser


def _read(path: str | None) -> str:
    if not path or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _documents(text: str) -> tuple[list[object], bool]:
    text = text.strip()
    if not text:
        raise ValueError("JSON input is empty")
    try:
        return [json.loads(text)], False
    except json.JSONDecodeError as initial:
        documents = []
        for line in text.splitlines():
            if line.strip():
                try:
                    documents.append(json.loads(line))
                except json.JSONDecodeError:
                    raise initial from None
        if not documents:
            raise
        return documents, True


def _write(
    documents: list[object],
    *,
    is_jsonl: bool,
    transform: Callable[[object], object],
    indent: int | None = None,
) -> None:
    if is_jsonl:
        if indent is not None:
            raise ValueError("--indent cannot be used with JSONL input")
        for document in documents:
            print(json.dumps(transform(document), separators=(",", ":")))
    else:
        print(json.dumps(transform(documents[0]), indent=indent, separators=None if indent else (",", ":")))


def _without_nulls(value: object) -> object:
    if isinstance(value, dict):
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value if item is not None]
    return value


def parse_remove_nulls_args() -> argparse.Namespace:
    parser = _parser(USAGE["remove_nulls"])
    parser.add_argument("--indent", type=int)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def remove_nulls() -> None:
    args = parse_remove_nulls_args()
    documents, jsonl = _documents(_read(args.path))
    _write(documents, is_jsonl=jsonl, transform=_without_nulls, indent=args.indent)
