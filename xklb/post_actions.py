import re, shlex, shutil
from pathlib import Path
from typing import Optional

import humanize

from xklb.utils import devices, file_utils, iterables, processes, sql_utils
from xklb.utils.log_utils import log

try:
    import tkinter  # noqa

    from xklb.utils import gui

except ModuleNotFoundError:
    gui = None


def mv_to_keep_folder(args, media_file: str) -> None:
    keep_path = Path(args.keep_dir)
    if not keep_path.is_absolute():
        kp = re.match(args.shallow_organize + "(.*?)/", media_file)
        if kp:
            keep_path = Path(kp[0], f"{args.keep_dir}/")
        elif Path(media_file).parent.match(f"*/{args.keep_dir}/*"):
            return
        else:
            keep_path = Path(media_file).parent / f"{args.keep_dir}/"

    keep_path.mkdir(exist_ok=True)

    try:
        new_path = shutil.move(media_file, keep_path)
    except shutil.Error as e:
        if "already exists" not in str(e):
            raise
        p = Path(media_file)
        new_path = Path(keep_path) / p.name

        src_size = p.stat().st_size
        dst_size = new_path.stat().st_size
        diff_size = humanize.naturalsize(src_size - dst_size)

        if src_size > dst_size:
            print("Source is larger than destination", diff_size)
        elif src_size < dst_size:
            print("Source is smaller than destination", diff_size)
        else:
            print("Source and destination are the same size", humanize.naturalsize(src_size))
        if args.post_action.upper().startswith("ASK_"):
            if devices.confirm("Replace destination file?"):
                file_utils.trash(new_path, detach=False)
                new_path = shutil.move(media_file, keep_path)
            else:
                return
        else:
            raise

    if getattr(args, "keep_cmd", None):
        processes.cmd_detach(shlex.split(args.keep_cmd), new_path)
    if hasattr(args, "db"):
        with args.db.conn:
            args.db.conn.execute("DELETE FROM media where path = ?", [new_path])
            args.db.conn.execute("UPDATE media set path = ? where path = ?", [new_path, media_file])


def delete_media(args, paths) -> int:
    paths = iterables.conform(paths)
    for p in paths:
        if p.startswith("http"):
            continue

        if getattr(args, "prefix", False):
            Path(p).unlink(missing_ok=True)
        else:
            file_utils.trash(p, detach=len(paths) < 30)

    if hasattr(args, "db"):
        return sql_utils.mark_media_deleted(args, paths)
    else:
        return len(paths)


class Action:
    KEEP = "KEEP"
    DELETE = "DELETE"
    DELETE_IF_AUDIOBOOK = "DELETE_IF_AUDIOBOOK"
    SOFTDELETE = "SOFTDELETE"
    MOVE = "MOVE"


class AskAction:
    ASK_KEEP = (Action.KEEP, Action.DELETE)
    ASK_MOVE = (Action.MOVE, Action.KEEP)
    ASK_DELETE = (Action.DELETE, Action.KEEP)
    ASK_SOFTDELETE = (Action.SOFTDELETE, Action.KEEP)
    ASK_MOVE_OR_DELETE = (Action.MOVE, Action.DELETE)


def post_act(
    args, media_file: str, action: Optional[str] = None, geom_data=None, media_len=0, player_exit_code=None
) -> None:
    def handle_delete_action():
        if media_file.startswith("http"):
            sql_utils.mark_media_deleted(args, media_file)
        else:
            delete_media(args, media_file)

    def handle_soft_delete_action():
        sql_utils.mark_media_deleted(args, media_file)

    def handle_move_action():
        if not media_file.startswith("http"):
            mv_to_keep_folder(args, media_file)

    def handle_ask_action(ask_action: str):
        true_action, false_action = getattr(AskAction, ask_action)
        if args.exit_code_confirm and player_exit_code is not None:
            log.info("%s remaining", media_len)
            response = player_exit_code
        elif gui and args.gui:
            response = gui.askkeep(
                media_file,
                media_len,
                geom_data,
                true_action=true_action,
                false_action=false_action,
            )
        else:
            response = devices.confirm(true_action.title() + "?")
        confirmed_action = true_action if response else false_action
        if geom_data is not None:
            log.warning("%s: %s", confirmed_action, media_file)
        post_act(args, media_file, action=confirmed_action)  # answer the question

    action = action or args.post_action
    action = action.upper()

    if action == "NONE":
        action = Action.KEEP

    if action == Action.KEEP:
        pass
    elif action == Action.DELETE:
        handle_delete_action()
    elif action == Action.DELETE_IF_AUDIOBOOK:
        if "audiobook" in media_file.lower():
            handle_delete_action()
    elif action == Action.SOFTDELETE:
        handle_soft_delete_action()
    elif action == Action.MOVE:
        handle_move_action()
    elif action.startswith("ASK_"):
        handle_ask_action(action)
    else:
        raise ValueError("Unrecognized action:", action)
