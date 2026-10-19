import argparse
import re
import sys

from library import usage
from library.utils import arggroups, argparse_utils
import pathlib


def _parser(usage_text: str) -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=usage_text)
    arggroups.debug(parser)
    return parser


def parse_border_args() -> argparse.Namespace:
    parser = _parser(usage.text_border)
    parser.add_argument("--char", default="#", help="Border character")
    parser.add_argument("--padding", type=int, default=2)
    parser.add_argument("text", nargs="*")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def border() -> None:
    args = parse_border_args()
    if len(args.char) != 1:
        raise ValueError("--char must be exactly one character")
    if args.padding < 0:
        raise ValueError("--padding must not be negative")

    text = " ".join(args.text) if args.text else sys.stdin.read().rstrip("\n")
    lines = text.splitlines() or [""]
    width = max(len(line) for line in lines)
    edge = args.char * (width + (args.padding * 2) + 2)
    print(edge)
    for line in lines:
        print(f"{args.char}{' ' * args.padding}{line.ljust(width)}{' ' * args.padding}{args.char}")
    print(edge)


def clean_text(text: str, strip_chars: str, min_blank_lines: int = 3) -> str:
    if min_blank_lines < 1:
        raise ValueError("min_blank_lines must be at least one")

    strip_pattern = re.compile(f"[{re.escape(strip_chars)}]") if strip_chars else None
    lines = [(strip_pattern.sub("", line) if strip_pattern else line).rstrip() for line in text.splitlines()]
    blocks = []
    current_block = ""
    current_indent = ""
    blank_count = 0
    md_start = re.compile(r"^(\s*)([-*+>]|\d+\.|#+)\s+")

    def flush() -> None:
        nonlocal current_block, current_indent
        if current_block:
            blocks.append(current_indent + current_block)
            current_block = ""
            current_indent = ""

    for line in lines:
        if not line.strip():
            blank_count += 1
            continue

        if blank_count >= min_blank_lines:
            flush()
            if blocks and blocks[-1] != "":
                blocks.append("")
        elif blank_count and current_block:
            current_block += " "
        blank_count = 0

        match = md_start.match(line)
        if match:
            flush()
            current_indent = match.group(1)
            marker = match.group(2)
            content = line[len(current_indent) + len(marker) :].strip()
            current_block = f"{marker} {re.sub(r' {2,}', ' ', content)}"
        else:
            cleaned_line = re.sub(r" {2,}", " ", line.strip())
            if current_block:
                current_block += f" {cleaned_line}"
            else:
                current_block = cleaned_line

    flush()

    return "\n".join(blocks).strip()


def parse_clean_args() -> argparse.Namespace:
    parser = _parser(usage.text_clean)
    parser.add_argument("--strip-chars", default="┃┃|│")
    parser.add_argument(
        "--min-blank-lines",
        type=int,
        default=3,
        help="Number of blank lines required to start a new paragraph",
    )
    parser.add_argument("input_path", nargs="?", default="-")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def clean() -> None:
    args = parse_clean_args()
    if args.input_path == "-":
        text = sys.stdin.read()
    else:
        text = pathlib.Path(args.input_path).read_text(encoding="utf-8")
    result = clean_text(text, args.strip_chars, args.min_blank_lines)
    if result:
        print(result)
