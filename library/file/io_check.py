import argparse
import errno
import os
from dataclasses import dataclass

from library import usage
from library.utils import arggroups, argparse_utils, devices, shell_utils

DEFAULT_CHUNK_SIZE = 256 * 1024 * 1024


@dataclass(frozen=True)
class IOCheckResult:
    path: str
    error: OSError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def is_io_error(self) -> bool:
        return self.error is not None and self.error.errno == errno.EIO


def read_in_chunks(file_object, chunk_size: int = DEFAULT_CHUNK_SIZE):
    if chunk_size < 1:
        raise ValueError("chunk_size must be greater than zero")

    while True:
        data = file_object.read(chunk_size)
        if not data:
            break
        yield data


def check_file(path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> IOCheckResult:
    path = os.fspath(path)
    try:
        with open(path, "rb") as file_object:
            for _ in read_in_chunks(file_object, chunk_size):
                pass
    except OSError as error:
        return IOCheckResult(path, error)
    return IOCheckResult(path)


def check_paths(paths, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[IOCheckResult]:
    return [check_file(path, chunk_size=chunk_size) for path in paths]


def _print_result(result: IOCheckResult) -> None:
    if result.is_io_error:
        print(result.path)
    elif result.error is not None:
        print(f"{result.path}: {result.error}")


def trash_io_errors(args, results: list[IOCheckResult]) -> None:
    if not getattr(args, "delete_files", False):
        return

    corrupt_paths = [result.path for result in results if result.is_io_error]
    if not corrupt_paths:
        return

    if (
        not getattr(args, "simulate", False)
        and not getattr(args, "no_confirm", False)
        and not devices.confirm(f"Move {len(corrupt_paths)} files with input/output errors to trash?")
    ):
        return

    for path in corrupt_paths:
        shell_utils.trash(args, path, detach=False)


def add_filesystem_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--filesystem",
        "--io",
        "--fs",
        action="store_true",
        help="Read files from the underlying filesystem instead of decoding media",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.io_check)
    add_filesystem_arg(parser)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Number of bytes to read at a time (default: 256 MiB)",
    )
    parser.add_argument("--remove", dest="delete_files", action="store_true", help="Alias for --delete-files")
    arggroups.capability_delete(parser)
    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)

    args = parser.parse_intermixed_args()
    if args.chunk_size < 1:
        parser.error("--chunk-size must be greater than zero")
    arggroups.args_post(args, parser)
    return args


def io_check(args: argparse.Namespace | None = None) -> None:
    args = args or parse_args()
    results = check_paths(shell_utils.gen_paths(args), chunk_size=args.chunk_size)
    for result in results:
        _print_result(result)
    trash_io_errors(args, results)


raw_check = io_check
check_io = io_check
