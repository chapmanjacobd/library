import argparse, shlex, sys, tempfile
from pathlib import Path
from shutil import which

from library import usage
from library.utils import arggroups, argparse_utils, devices, processes


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.pdf_header)
    parser.add_argument("header", help="Markdown/text rendered onto every PDF page")
    parser.add_argument("paths", nargs="+", metavar="INPUT.pdf")
    parser.add_argument("--output-path", "-o", help="Output PDF file (only valid for one input)")
    parser.add_argument(
        "--open",
        dest="open_output",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Open generated PDFs with dragondrop",
    )
    arggroups.clobber(parser)
    arggroups.debug(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    return args


def _require_commands(*commands: str) -> None:
    missing = [command for command in commands if which(command) is None]
    if missing:
        print(f"Required command(s) not found: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)


def process_path(args, path: str, output_path: str | None = None) -> str:
    source = Path(path)
    destination = Path(output_path) if output_path else source.with_name(f"{source.stem}.header.pdf")
    destination = Path(devices.clobber_new_file(args, str(destination)))

    with tempfile.TemporaryDirectory(prefix="library-pdf-header-") as temp_dir:
        header_source = Path(temp_dir) / "header.md"
        header_pdf = Path(temp_dir) / "header.pdf"
        header_source.write_text(args.header, encoding="utf-8")
        pandoc_command = ["pandoc", str(header_source), "-o", str(header_pdf)]
        pdftk_command = ["pdftk", str(source), "multistamp", str(header_pdf), "output", str(destination)]

        if args.simulate:
            print(shlex.join(pandoc_command))
            print(shlex.join(pdftk_command))
            return str(destination)

        processes.cmd(*pandoc_command, limit_ram=True, nice=6)
        processes.cmd(*pdftk_command, limit_ram=True, nice=6)

    if not destination.exists():
        message = f"pdftk did not create {destination}"
        raise FileNotFoundError(message)
    if args.open_output:
        _require_commands("dragondrop")
        processes.cmd_detach("dragondrop", str(destination))
    print(f"Saved {destination}")
    return str(destination)


def pdf_header() -> None:
    args = parse_args()
    _require_commands("pandoc", "pdftk")
    if args.output_path and len(args.paths) != 1:
        raise SystemExit("--output-path requires exactly one input PDF")
    for path in args.paths:
        process_path(args, path, args.output_path)
