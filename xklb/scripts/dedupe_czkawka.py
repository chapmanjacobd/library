#!/usr/bin/python3

import argparse, difflib, os, re, shutil, subprocess, sys, time
from pathlib import Path

import humanize
from screeninfo import get_monitors

from xklb import utils
from xklb.utils import log


def backup_and_read_file(file_path):
    backup_filename = file_path + ".bak"
    if not os.path.exists(backup_filename):
        try:
            shutil.copy2(file_path, backup_filename)
        except Exception as e:
            print(f"Failed to create backup file: {e}")

    with open(file_path, "r") as file:
        content = file.read()
    return content


def extract_dupe_groups(content):
    first_newline_index = content.find("\n")

    if first_newline_index != -1 and "similar friends" in content[:first_newline_index].strip().lower():
        content = content[first_newline_index + 1 :]

    groups = re.split(r"(-+MESSAGES-+\n+)", content)[0].split("\n\n")
    return groups


def parse_czkawka_line(line):
    image_pattern = r"^(.+) - (\d+x\d+) - (\d+(?:\.\d+)?|\d+) ([KMG]iB) - .+$"
    video_pattern = r"^(.+) - (\d+(?:\.\d+)?|\d+) ([KMG]iB)$"

    image_match = re.match(image_pattern, line)
    if image_match:
        path, resolution, size_value, size_unit = image_match.groups()
        return path.strip(), float(size_value), size_unit

    video_match = re.match(video_pattern, line)
    if video_match:
        path, size_value, size_unit = video_match.groups()
        return path.strip(), float(size_value), size_unit

    raise ValueError("Could not detect file style")


def extract_group_data(group_content):
    paths_and_sizes = []
    groups = group_content.split("\n")
    if len(groups) < 2:
        return
    for match in groups:
        if match == "":
            continue

        path, size_value, size_unit = parse_czkawka_line(match)
        if size_unit == "GiB":
            size_value *= 1024 * 1024 * 1024
        elif size_unit == "MiB":
            size_value *= 1024 * 1024
        elif size_unit == "KiB":
            size_value *= 1024
        paths_and_sizes.append({"path": path, "size": size_value})
    return paths_and_sizes


def truncate_file_before_match(filename, match_string):
    with open(filename, "r") as file:
        lines = file.readlines()
    matching_lines = [i for i, line in enumerate(lines) if match_string in line]

    if len(matching_lines) == 1:
        line_index = matching_lines[0]
        with open(filename, "w") as file:
            file.write("".join(lines[line_index - 1 :]))
        print(f"Progress saved. File truncated before the line containing: '{match_string}'")
        remaining = sum(1 for s in lines[line_index - 1 :] if s == "\n") - 2
        print(f"{remaining} left to check")
    elif len(matching_lines) == 0:
        print(f"Match not found in the file: '{match_string}'")
    else:
        print(f"Multiple matches found in the file for: '{match_string}'")


def side_by_side_mpv(args, left_side, right_side):
    # Get the size of the first connected display
    monitors = get_monitors()
    if not monitors:
        print("No connected displays found.")
        return

    display_width = monitors[0].width
    mpv_width = display_width // 2

    mpv_options = [
        "--save-position-on-quit=no",
        "--no-resume-playback",
        "--image-display-duration=inf",
        "--script-opts=osc-visibility=always",
        f"--start={args.start}",
        f"--volume={args.volume}",
    ]

    left_mpv_process = subprocess.Popen(
        ["mpv", left_side, f"--geometry={mpv_width}x{monitors[0].height}+0+0", *mpv_options],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    right_mpv_process = subprocess.Popen(
        ["mpv", right_side, f"--geometry={mpv_width}x{monitors[0].height}+{mpv_width}+0", *mpv_options],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Monitor the processes and terminate the other one when one finishes
    while True:
        if left_mpv_process.poll() is not None or right_mpv_process.poll() is not None:
            break
        time.sleep(0.1)

    # Terminate the other process
    if left_mpv_process.poll() is None:
        left_mpv_process.terminate()
    if right_mpv_process.poll() is None:
        right_mpv_process.terminate()


def mv_to_keep_folder(args, d) -> None:
    keep_path = Path(args.keep_dir)
    keep_path.mkdir(exist_ok=True)

    media_file = d["path"]

    try:
        new_path = shutil.move(media_file, keep_path)
    except shutil.Error as e:
        if "already exists" not in str(e):
            raise
        p = Path(media_file)
        new_path = Path(keep_path) / p.name

        src_size = d["size"]
        dst_size = new_path.stat().st_size
        diff_size = humanize.naturalsize(src_size - dst_size)

        if src_size > dst_size:
            print("Source is larger than destination", diff_size)
        elif src_size < dst_size:
            print("Source is smaller than destination", diff_size)
        else:
            print("Source and destination are the same size", humanize.naturalsize(src_size))
        if utils.confirm("Replace destination file?"):
            utils.trash(new_path, detach=False)
            new_path = shutil.move(media_file, keep_path)

    log.info(f"{new_path}: new location")


def group_and_delete(args, groups):
    is_interactive = not any([args.all_keep, args.all_left, args.all_right, args.all_delete])

    for group_content in groups:
        if group_content == "":
            continue

        group = extract_group_data(group_content)
        if group is None:
            continue

        def delete_dupe(d, detach=is_interactive):
            utils.trash(d["path"], detach=detach)
            log.info(f"{d['path']}: Deleted")

        group.sort(key=lambda x: x["size"], reverse=True)
        left = group[0]

        dups = group[1:]
        kept_paths = []
        while len(dups) > 0:
            right = dups.pop()

            if right["path"] == left["path"]:
                continue

            if not os.path.exists(right["path"]):
                log.debug(f"{right['path']}: not found")
                continue

            if not os.path.exists(left["path"]):
                log.debug(f"{left['path']}: not found")
                left = right
                continue

            print(left["path"], humanize.naturalsize(left["size"]))
            print(right["path"], humanize.naturalsize(right["size"]))

            if args.auto_select_min_ratio < 1.0:
                similar_ratio = difflib.SequenceMatcher(
                    None, os.path.basename(left["path"]), os.path.basename(right["path"])
                ).ratio()
                if similar_ratio >= args.auto_select_min_ratio or any(
                    s in left["path"] and s in right["path"] for s in ["Goldmines_Bollywood"]
                ):
                    delete_dupe(right)
                continue

            if not is_interactive:
                if args.all_left:
                    kept_paths.append(left)
                    delete_dupe(right)
                elif args.all_right:
                    kept_paths.append(right)
                    delete_dupe(left)
                    left = right
                elif args.all_delete:
                    delete_dupe(left)
                    delete_dupe(right)
                continue

            side_by_side_mpv(args, left["path"], right["path"])
            while True:
                user_input = (
                    input(
                        "Names are pretty different. Keep which files? (l Left/r Right/k Keep both/d Delete both) [default: l]: "
                    )
                    .strip()
                    .lower()
                )
                if args.all_keep or user_input in ("k", "keep"):
                    kept_paths.append(left)
                    kept_paths.append(right)
                    break
                elif args.all_left or user_input in ("l", "left", ""):
                    kept_paths.append(left)
                    delete_dupe(right)
                    break
                elif args.all_right or user_input in ("r", "right"):
                    kept_paths.append(right)
                    delete_dupe(left, detach=False)
                    break
                elif args.all_delete or user_input in ("d", "delete"):
                    delete_dupe(right)
                    delete_dupe(left, detach=False)
                    break
                elif user_input in ("q", "quit"):
                    truncate_file_before_match(args.file_path, left["path"])
                    sys.exit(0)
                else:
                    print("Invalid input. Please type 'left', 'right', 'keep', 'delete', or 'quit' and enter")

            if len(dups) > 1:
                left = dups.pop()

        if args.keep_dir:
            for d in utils.list_dict_unique(kept_paths, ["path"]):
                if os.path.exists(d["path"]):
                    mv_to_keep_folder(args, d)

        print()


def czkawka_dedupe():
    parser = argparse.ArgumentParser(description="Cleanup duplicate files based on their sizes.")
    parser.add_argument("file_path", help="Path to the text file containing the file list.")
    parser.add_argument(
        "--auto-select-min-ratio",
        type=float,
        default=1.0,
        help="Automatically select largest file if files have similar basenames. A sane value is in the range of 0.7~0.9",
    )
    parser.add_argument("--start", default="80%")
    parser.add_argument("--volume", default="70", type=float)
    parser.add_argument("--keep-dir", "--keepdir", help=argparse.SUPPRESS)
    parser.add_argument("--all-keep", action="store_true")
    parser.add_argument("--all-left", action="store_true")
    parser.add_argument("--all-right", action="store_true")
    parser.add_argument("--all-delete", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    content = backup_and_read_file(args.file_path)
    groups = extract_dupe_groups(content)
    group_and_delete(args, groups)
