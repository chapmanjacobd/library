import shlex
from pathlib import Path

from library.mediadb import db_history, db_media
from library.utils import devices, file_utils, iterables, processes
from library.utils.log_utils import log

try:
    import tkinter  # noqa

    from library.utils import gui

except ModuleNotFoundError:
    gui = None


def mv_to_keep_folder(args, src: str) -> str:
    keep_dir = Path(args.keep_dir)
    p = Path(src)
    if keep_dir.is_absolute():
        if p.parent.is_relative_to(keep_dir):
            return src  # file already in a matching keep_dir
    else:  # relative to existing media
        if args.keep_dir in p.parent.parts:
            return src  # file already in a matching keep_dir
        keep_dir = p.parent / args.keep_dir

    keep_dir = keep_dir.resolve()
    keep_dir.mkdir(exist_ok=True)

    dest = file_utils.rel_move(args, src, keep_dir)
    if src == dest:
        return src

    if dest and hasattr(args, "db") and args.db:
        with args.db.conn:
            args.db.conn.execute("DELETE FROM media where path = ?", [dest])  # remove any existing records
            args.db.conn.execute("UPDATE media set path = ? where path = ?", [dest, src])

    return dest or src


def delete_media(args, paths) -> int:
    paths = iterables.conform(paths)
    for p in paths:
        if p.startswith("http"):
            continue

        if getattr(args, "prefix", False):
            Path(p).unlink(missing_ok=True)
        else:
            file_utils.trash(args, p, detach=len(paths) < 30)

    if hasattr(args, "db") and args.db:
        return db_media.mark_media_deleted(args, paths)
    else:
        return len(paths)


class Action:
    NONE = "NONE"
    DELETE = "DELETE"
    DELETE_IF_AUDIOBOOK = "DELETE_IF_AUDIOBOOK"
    SOFTDELETE = "SOFTDELETE"
    MOVE = "MOVE"


class AskAction:
    ASK_MOVE = (Action.MOVE, Action.NONE)
    ASK_DELETE = (Action.DELETE, Action.NONE)
    ASK_SOFTDELETE = (Action.SOFTDELETE, Action.NONE)
    ASK_MOVE_OR_DELETE = (Action.MOVE, Action.DELETE)


def normal_action(args, media_file: str, action, handle_ask_action=None):
    def handle_delete_action():
        if media_file.startswith("http"):
            db_media.mark_media_deleted(args, media_file)
        else:
            delete_media(args, media_file)

    def handle_soft_delete_action():
        db_media.mark_media_deleted(args, media_file)

    action = action or args.post_action
    action = action.upper()

    if action == "KEEP":
        action = Action.NONE

    if action == Action.NONE:
        pass
    elif action == Action.DELETE:
        handle_delete_action()
    elif action == Action.DELETE_IF_AUDIOBOOK:
        if "audiobook" in media_file.lower():
            handle_delete_action()
    elif action == Action.SOFTDELETE:
        handle_soft_delete_action()
    elif action == Action.MOVE:
        if not media_file.startswith("http"):
            media_file = mv_to_keep_folder(args, media_file)
    elif action.startswith("ASK_"):
        if handle_ask_action is None:
            raise RuntimeError
        handle_ask_action(action)
    else:
        raise ValueError("Unrecognized action:", action)


def external_action(args, log_action, media_file, player_exit_code, player_process):
    player_exit_code_cmd = f"cmd{player_exit_code}"
    cmd = getattr(args, player_exit_code_cmd, None)
    if cmd:
        log_action(player_exit_code_cmd.upper() + " " + cmd)
        if cmd in ["pass", "mark-watched"]:
            pass
        elif cmd in ["soft-delete", "mark-deleted"]:
            db_media.mark_media_deleted(args, media_file)
        elif cmd in ["delete", "delete-files", "delete-file"]:
            if media_file.startswith("http"):
                db_media.mark_media_deleted(args, media_file)
            else:
                delete_media(args, media_file)
        elif cmd == "exit_multiple_playback":
            processes.player_exit(player_process)
        elif "{}" in cmd:
            processes.cmd_detach(media_file if s == "{}" else s for s in shlex.split(cmd))
        else:
            processes.cmd_detach(*shlex.split(cmd), media_file)
    elif player_exit_code > 0 and not args.ignore_errors and not (args.delete_unplayable and player_exit_code == 2):
        processes.player_exit(player_process)


def post_act(
    args, media_file: str, media_len=0, record_history=True, geom_data=None, player_process=None, action=None
) -> None:
    def log_action(confirmed_action):
        if args.exit_code_confirm and media_len > 0:
            log.warning("[%s]: %s (%s remaining)", confirmed_action, media_file, media_len)
        else:
            log.warning("[%s]: %s", confirmed_action, media_file)

    player_exit_code = getattr(player_process, "returncode", None) or 0

    if record_history and player_exit_code == 0 and args.db:
        db_history.add(args, [media_file], mark_done=True)

    if 0 < player_exit_code < 5 and not args.ignore_errors:
        if args.delete_unplayable and player_exit_code == 2:  #  https://mpv.io/manual/master/#exit-codes
            delete_media(args, [media_file])
        else:
            processes.player_exit(player_process)

    def handle_ask_action(ask_action: str):
        true_action, false_action = getattr(AskAction, ask_action)
        if args.exit_code_confirm and player_exit_code is not None:
            response = player_exit_code == 0
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
        log_action(confirmed_action)
        normal_action(args, media_file, action=confirmed_action)  # answer the question

    if player_exit_code < 5:
        normal_action(args, media_file, action=action, handle_ask_action=handle_ask_action)

    external_action(args, log_action, media_file, player_exit_code=player_exit_code, player_process=player_process)
