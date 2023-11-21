import argparse, difflib, os, re, shlex, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import humanize
from screeninfo import get_monitors

from xklb import post_actions
from xklb.media import media_player
from xklb.utils import consts, devices, file_utils, iterables, mpv_utils, processes
from xklb.utils.log_utils import log

left_mpv_socket = str(Path(consts.TEMP_SCRIPT_DIR) / f"mpv_socket_{consts.random_string()}")
right_mpv_socket = str(Path(consts.TEMP_SCRIPT_DIR) / f"mpv_socket_{consts.random_string()}")


def parse_args():
    parser = argparse.ArgumentParser(description="Cleanup duplicate files based on their sizes.")
    parser.add_argument("file_path", help="Path to the text file containing the file list.")
    parser.add_argument(
        "--auto-select-min-ratio",
        type=float,
        default=1.0,
        help="Automatically select largest file if files have similar basenames. A sane value is in the range of 0.7~0.9",
    )
    parser.add_argument("--start", default="15%")
    parser.add_argument("--volume", default="70", type=float)
    parser.add_argument("--keep-dir", "--keepdir", help=argparse.SUPPRESS)
    parser.add_argument("--exit-code-confirm", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--auto-seek", action="store_true")
    parser.add_argument("--override-player", "--player", "-player", help=argparse.SUPPRESS)
    parser.add_argument("--all-keep", action="store_true")
    parser.add_argument("--all-left", action="store_true")
    parser.add_argument("--all-right", action="store_true")
    parser.add_argument("--all-delete", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    return args


def backup_and_read_file(file_path):
    backup_filename = file_path + ".bak"
    if not os.path.exists(backup_filename):
        try:
            shutil.copy2(file_path, backup_filename)
        except Exception as e:
            print(f"Failed to create backup file: {e}")

    with open(file_path) as file:
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
        return None
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
    with open(filename) as file:
        lines = file.readlines()
    matching_lines = [i for i, line in enumerate(lines) if match_string in line]

    if len(matching_lines) == 1:
        line_index = matching_lines[0]
        with open(filename, "w") as file:
            file.write("".join(lines[line_index - 1 :]))
        print(f"Progress saved. File truncated before the line containing: '{match_string}'")
        remaining = sum(1 for s in lines[line_index - 1 :] if s == "\n") - 1
        num_videos = sum(1 for s in lines[line_index - 1 :] if s != "\n") - 12
        print(f"{remaining} groups (~{num_videos} videos) remain to check")
    elif len(matching_lines) == 0:
        print(f"Match not found in the file: '{match_string}'")
    else:
        print(f"Multiple matches found in the file for: '{match_string}'")


def side_by_side_mpv(args, left_side, right_side):
    monitors = get_monitors()
    if not monitors:
        print("No connected displays found.")
        return

    display = media_player.modify_display_size_for_taskbar(monitors[0])
    mpv_width = display.width // 2

    if args.auto_seek:
        from python_mpv_jsonipc import MPV

        mpv_kwargs = {
            "save_position_on_quit": False,
            "start": args.start,
        }

        left_mpv = MPV(ipc_socket=left_mpv_socket, geometry=f"{mpv_width}x{display.height}+0+0", **mpv_kwargs)
        right_mpv = MPV(
            ipc_socket=right_mpv_socket,
            geometry=f"{mpv_width}x{display.height}+{mpv_width}+0",
            **mpv_kwargs,
        )

        for x_mpv in (left_mpv, right_mpv):
            x_mpv.volume = args.volume
            x_mpv.command("script-message", "osc-visibility", "always")  # , "no-osd"

            @x_mpv.on_key_press("k")
            def keep_handler():
                print("keep")

            @x_mpv.on_key_press("d")
            def delete_handler():
                print("delete")

        left_mpv.play(left_side)
        right_mpv.play(right_side)

        def right_quit_callback():
            try:
                left_mpv.command("quit")
            except BrokenPipeError:
                pass

        left_mpv.quit_callback = right_mpv.terminate
        right_mpv.quit_callback = right_quit_callback  # they can't both be the same

        with ThreadPoolExecutor() as e:
            e.submit(mpv_utils.auto_seek, left_mpv)
            e.submit(mpv_utils.auto_seek, right_mpv, delay=0.4)

    else:
        mpv_options = [
            "--save-position-on-quit=no",
            "--no-resume-playback",
            "--image-display-duration=inf",
            "--script-opts=osc-visibility=always",
            f"--start={args.start}",
            f"--volume={args.volume}",
        ]

        left_mpv_process = subprocess.Popen(
            [
                "mpv",
                left_side,
                f"--input-ipc-server={left_mpv_socket}",
                f"--geometry={mpv_width}x{display.height}+0+0",
                *mpv_options,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        right_mpv_process = subprocess.Popen(
            [
                "mpv",
                right_side,
                f"--input-ipc-server={right_mpv_socket}",
                f"--geometry={mpv_width}x{display.height}+{mpv_width}+0",
                *mpv_options,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # if not all([Path(left_side).exists(), Path(right_side).exists()]):
        #     return  # race condition

        while True:  # Monitor the processes and terminate the other one when one finishes
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
    except FileNotFoundError:
        return
    except shutil.Error as e:
        if "already exists" not in str(e):
            raise
        p = Path(media_file)
        new_path = Path(keep_path) / p.name

        src_size = d["size"]
        dst_size = new_path.stat().st_size
        diff_size = humanize.naturalsize(src_size - dst_size, binary=True)

        if src_size > dst_size:
            print("Source is larger than destination", diff_size)
        elif src_size < dst_size:
            print("Source is smaller than destination", diff_size)
        else:
            print("Source and destination are the same size", humanize.naturalsize(src_size, binary=True))
        if devices.confirm("Replace destination file?"):
            file_utils.trash(new_path, detach=False)
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
            file_utils.trash(d["path"], detach=detach)
            log.info(f"{d['path']}: Deleted")

        group.sort(key=lambda x: x["size"], reverse=True)
        left = group[0]

        dups = group[1:]
        kept_dups = []
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

            print(left["path"], humanize.naturalsize(left["size"], binary=True))
            print(right["path"], humanize.naturalsize(right["size"], binary=True))

            if args.auto_select_min_ratio < 1.0:
                similar_ratio = difflib.SequenceMatcher(
                    None,
                    os.path.basename(left["path"]),
                    os.path.basename(right["path"]),
                ).ratio()
                if similar_ratio >= args.auto_select_min_ratio or any(
                    s in left["path"] and s in right["path"] for s in ["Goldmines_Bollywood"]
                ):
                    delete_dupe(right)
                continue

            if not is_interactive:
                if args.all_left:
                    kept_dups.append(left)
                    delete_dupe(right)
                elif args.all_right:
                    kept_dups.append(right)
                    delete_dupe(left)
                    left = right
                elif args.all_delete:
                    delete_dupe(left)
                    delete_dupe(right)
                continue

            is_next_iter_not_last = len(dups) > 1

            if args.override_player:
                for path in (left["path"], right["path"]):
                    r = processes.cmd(*shlex.split(args.override_player), path, strict=False)
                    if r.returncode == 0:
                        post_actions.post_act(
                            args,
                            path,
                            action="ASK_MOVE_OR_DELETE" if args.keep_dir else "ASK_DELETE",
                            player_exit_code=r.returncode,
                        )
                    else:
                        truncate_file_before_match(args.file_path, left["path"])
                        log.warning("Player exited with code %s", r.returncode)
                        raise SystemExit(r.returncode)
            else:
                side_by_side_mpv(args, left["path"], right["path"])
                while True:
                    devices.clear_input()
                    user_input = (
                        input("Keep which files? (l Left/r Right/k Keep both/d Delete both) [default: l]: ")
                        .strip()
                        .lower()
                    )
                    if args.all_keep or user_input in ("k", "keep"):
                        kept_dups.append(left)
                        kept_dups.append(right)
                        break
                    elif args.all_left or user_input in ("l", "left", ""):
                        kept_dups.append(left)
                        delete_dupe(right, detach=is_next_iter_not_last)
                        break
                    elif args.all_right or user_input in ("r", "right"):
                        kept_dups.append(right)
                        delete_dupe(left, detach=is_next_iter_not_last)
                        break
                    elif args.all_delete or user_input in ("d", "delete"):
                        delete_dupe(right, detach=is_next_iter_not_last)
                        delete_dupe(left, detach=is_next_iter_not_last)
                        break
                    elif user_input in ("q", "quit"):
                        truncate_file_before_match(args.file_path, left["path"])
                        sys.exit(0)
                    else:
                        print("Invalid input. Please type 'left', 'right', 'keep', 'delete', or 'quit' and enter")

            if len(dups) > 1:
                left = dups.pop()
            elif len(dups) == 1 and len(kept_dups) > 0:
                left = kept_dups[-1]

        if args.keep_dir:
            for d in iterables.list_dict_unique(kept_dups, ["path"]):
                if os.path.exists(d["path"]):
                    mv_to_keep_folder(args, d)

        print()


def czkawka_dedupe():
    args = parse_args()

    content = backup_and_read_file(args.file_path)
    groups = extract_dupe_groups(content)
    group_and_delete(args, groups)
