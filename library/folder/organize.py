import argparse
import os
from collections import defaultdict
from pathlib import Path

from library import usage
from library.folder import merge_mv
from library.utils import arggroups, argparse_utils, consts
from library.utils.log_utils import log

MIXED_SCORE = 0.5


def get_file_extension(filepath) -> str:
    return os.path.splitext(os.fspath(filepath))[1].lstrip(".").lower()


def categorize_file(filename) -> str:  # noqa: PLR0911
    ext = get_file_extension(filename)

    if ext in consts.PLAIN_EXTENSIONS | consts.CALIBRE_EXTENSIONS:
        return "books"
    if ext in consts.AUDIO_ONLY_EXTENSIONS:
        return "audio"
    if ext in consts.VIDEO_EXTENSIONS | consts.IMAGE_ANIMATION_EXTENSIONS:
        return "video"
    if ext in consts.IMAGE_EXTENSIONS:
        return "images"
    if ext in consts.ARCHIVE_EXTENSIONS:
        return "archives"
    if ext in consts.HTML_SIDECAR_EXTENSIONS | consts.OCRMYPDF_EXTENSIONS | consts.OCR_EXTENSIONS:
        return "documents"
    return "other"


def analyze_folder(files) -> str:
    if not files:
        return "empty"

    category_counts = defaultdict(int)
    category_sizes = defaultdict(int)
    for file_path in files:
        category = categorize_file(file_path)
        category_counts[category] += 1
        category_sizes[category] += os.stat(file_path).st_size

    total_files = sum(category_counts.values())
    total_size = sum(category_sizes.values())
    if total_files == 0:
        return "empty"

    category_scores = {
        category: (count / total_files) * ((category_sizes[category] / total_size if total_size else 0) * 4)
        for category, count in category_counts.items()
    }
    main_category, main_score = max(category_scores.items(), key=lambda item: item[1], default=("unknown", 0))
    if len(category_scores) > 1 and main_score < MIXED_SCORE:
        return "mixed"
    return main_category


def _folders(paths, depth: int) -> list[Path]:
    folders = []
    for path in paths:
        folder = Path(path)
        if not folder.is_dir():
            continue
        if depth > 0:
            start_depth = len(folder.parts)
            folders.extend(sp for sp in folder.rglob("*") if depth == len(sp.parts) - start_depth and sp.is_dir())
        else:
            folders.append(folder)
    return folders


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.organize_folders)
    parser.add_argument("--depth", "-D", type=int, default=0, help="Organize folders this many levels below each path")
    parser.add_argument(
        "--move",
        "--destination",
        type=Path,
        help="Parent directory for the generated category folders (default: each folder's parent)",
    )
    arggroups.mmv_folders(parser)
    parser.add_argument("--move-sizes", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--move-limit", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--move-exclude", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--move-include", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    arggroups.mmv_folders_post(args)
    return args


def organize() -> None:
    args = parse_args()
    if args.depth < 0:
        raise ValueError("--depth must be zero or greater")

    for folder in _folders(args.paths, args.depth):
        files = [path for path in folder.rglob("*") if not path.is_dir()]
        category = analyze_folder(files)
        parent = args.move or folder.parent
        if not args.move:
            for _ in range(args.depth):
                parent = parent.parent

        target_path = parent / category / folder.name
        try:
            target_path.relative_to(folder)
        except ValueError:
            pass
        else:
            log.warning("Skipping destination inside source folder: %s", target_path)
            continue

        if args.simulate:
            for path in files:
                print(path)
                print("-->", target_path / path.relative_to(folder))
            continue

        if not args.simulate and not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
        merge_mv.move(args, [str(folder)], str(target_path))
