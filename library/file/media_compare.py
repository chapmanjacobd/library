import argparse
import hashlib
import shutil
import subprocess

from library.utils import arggroups, argparse_utils

USAGE = {
    "media_hash": """library file media-hash PATH ...

    Hash decoded audio/video streams with ffmpeg's framemd5 muxer.
""",
    "media_compare": """library file media-compare PATH PATH [PATH ...]

    Compare decoded audio/video streams. Exit with status 1 when any media
    differs.
""",
}
MIN_MEDIA_PATHS = 2


def _parser(usage: str) -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.debug(parser)
    parser.add_argument("paths", nargs="+")
    return parser


def _frame_md5(path: str) -> bytes:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for media hashing and comparison")

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-v",
        "error",
        "-i",
        path,
        "-map",
        "0",
        "-f",
        "framemd5",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        error = result.stderr.decode(errors="replace").strip()
        message = f"ffmpeg could not decode {path}: {error or 'unknown error'}"
        raise RuntimeError(message)

    return b"\n".join(line for line in result.stdout.splitlines() if not line.startswith(b"#"))


def media_digest(path: str) -> str:
    return hashlib.sha256(_frame_md5(path)).hexdigest()


def parse_media_hash_args() -> argparse.Namespace:
    parser = _parser(USAGE["media_hash"])
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def media_hash() -> None:
    args = parse_media_hash_args()
    for path in args.paths:
        print(media_digest(path), path, sep="\t")


def parse_media_compare_args() -> argparse.Namespace:
    parser = _parser(USAGE["media_compare"])
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    if len(args.paths) < MIN_MEDIA_PATHS:
        parser.error("at least two paths are required")
    return args


def media_compare() -> None:
    args = parse_media_compare_args()
    digests = {path: media_digest(path) for path in args.paths}
    if len(set(digests.values())) == 1:
        print("Media streams are equal")
        return

    print("Media streams differ")
    for path, digest in digests.items():
        print(digest, path, sep="\t")
    raise SystemExit(1)
