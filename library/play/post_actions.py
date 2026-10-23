import os, shlex
from pathlib import Path

from library.database.manage import db_history, db_media
from library.utils import devices, iterables, processes, shell_utils
from library.utils.log_utils import log

TRASH_DETACH_PATH_LIMIT = 30
MAX_PLAYER_EXIT_CODE = 4
UNPLAYABLE_EXIT_CODE = 2
CONFIRM_EXIT_CODE = 4

try:
    import tkinter  # noqa

    from library.utils import gui

except ModuleNotFoundError:
    gui = None


def mv_to_keep_folder(args, src: str) -> str:
    keep_dir = str(args.keep_dir)
    if not args.keep_dir.startswith(":/"):
        p = Path(src)
        if os.path.isabs(keep_dir):
            if p.parent.is_relative_to(keep_dir):
                return src  # file already in a matching keep_dir
        else:  # relative to existing media
            if args.keep_dir in p.parent.parts:
                return src  # file already in a matching keep_dir
            keep_dir = str(p.parent / args.keep_dir)

    dest = shell_utils.rel_move(args, src, keep_dir)
    if src == dest:
        return src

    if not getattr(args, "simulate", False):
        os.makedirs(os.path.dirname(dest), exist_ok=True)

    if dest and not getattr(args, "simulate", False) and hasattr(args, "db") and args.db:
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
            devices.unlink(args, p)
        else:
            shell_utils.trash(args, p, detach=len(paths) < TRASH_DETACH_PATH_LIMIT)

    if not getattr(args, "simulate", False) and hasattr(args, "db") and args.db:
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


def _log_action(args, media_file, media_len, confirmed_action):
    if args.exit_code_confirm and media_len > 0:
        log.warning("[%s]: %s (%s remaining)", confirmed_action, media_file, media_len)
    else:
        log.warning("[%s]: %s", confirmed_action, media_file)


def _handle_ask_action(args, media_file, media_len, geom_data, player_exit_code, ask_action):
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
    _log_action(args, media_file, media_len, confirmed_action)
    return confirmed_action


def _normal_action(args, media_file: str, action, media_len, geom_data, player_exit_code):
    def handle_delete_action():
        if media_file.startswith("http"):
            db_media.mark_media_deleted(args, media_file)
        else:
            delete_media(args, media_file)

    action = (action or args.post_action).upper()
    if action == "KEEP":
        action = Action.NONE

    if action == Action.DELETE:
        handle_delete_action()
    elif action == Action.DELETE_IF_AUDIOBOOK:
        if "audiobook" in media_file.lower():
            handle_delete_action()
    elif action == Action.SOFTDELETE:
        db_media.mark_media_deleted(args, media_file)
    elif action == Action.MOVE:
        if not media_file.startswith("http"):
            mv_to_keep_folder(args, media_file)
    elif action.startswith("ASK_"):
        confirmed_action = _handle_ask_action(
            args, media_file, media_len, geom_data, player_exit_code, action
        )
        _normal_action(args, media_file, confirmed_action, media_len, geom_data, player_exit_code)
    elif action != Action.NONE:
        raise ValueError("Unrecognized action:", action)


def _handle_player_exit(args, media_file, player_process, player_exit_code):
    if player_exit_code == 0 or (player_exit_code in (1, 2, 3) and args.ignore_errors):
        return
    if player_exit_code == UNPLAYABLE_EXIT_CODE and args.delete_unplayable:
        delete_media(args, [media_file])
    elif player_exit_code == CONFIRM_EXIT_CODE and args.exit_code_confirm:
        log.debug("exit_code_confirm and exit code 4")
    else:
        processes.player_exit(player_process)


def _handle_external_command(args, media_file, player_process, player_exit_code_cmd, external_cmd, media_len):
    _log_action(args, media_file, media_len, player_exit_code_cmd.upper() + " " + external_cmd)
    if args.simulate:
        print("Would run:", external_cmd, media_file)
    elif external_cmd in ["pass", "mark-watched"]:
        return
    elif external_cmd in ["soft-delete", "mark-deleted"]:
        db_media.mark_media_deleted(args, media_file)
    elif external_cmd in ["delete", "delete-files", "delete-file"]:
        if media_file.startswith("http"):
            db_media.mark_media_deleted(args, media_file)
        else:
            delete_media(args, media_file)
    elif external_cmd == "exit_multiple_playback":
        processes.player_exit(player_process)
    elif "{}" in external_cmd:
        processes.cmd_detach(media_file if part == "{}" else part for part in shlex.split(external_cmd))
    else:
        processes.cmd_detach(*shlex.split(external_cmd), media_file)


def post_act(
    args, media_file: str, media_len=0, record_history=True, geom_data=None, player_process=None, action=None
) -> None:
    player_exit_code = getattr(player_process, "returncode", None) or 0
    if record_history and player_exit_code == 0 and args.db and not getattr(args, "simulate", False):
        db_history.add(args, [media_file], mark_done=True)

    player_exit_code_cmd = f"cmd{player_exit_code}"
    external_cmd = getattr(args, player_exit_code_cmd, None)
    if player_exit_code <= MAX_PLAYER_EXIT_CODE:
        _handle_player_exit(args, media_file, player_process, player_exit_code)
        _normal_action(args, media_file, action, media_len, geom_data, player_exit_code)
    elif external_cmd:
        _handle_external_command(
            args, media_file, player_process, player_exit_code_cmd, external_cmd, media_len
        )
    else:
        processes.player_exit(player_process)
