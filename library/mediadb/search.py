import argparse, textwrap
from copy import deepcopy
from itertools import groupby

from library.playback import media_player, media_printer
from library.utils import arggroups, argparse_utils, consts, iterables, printing, processes
from library.utils.log_utils import log
from library.utils.sqlgroups import construct_captions_search_query

USAGE = {
    'search': """library captions DATABASE QUERY

    Search text databases and subtitles

        library captions fts.db boil
            7 captions
            /mnt/d/70_Now_Watching/DidubeTheLastStop-720p.mp4
               33:46 I brought a real stainless steel boiler
               33:59 The world is using only stainless boilers nowadays
               34:02 The boiler is old and authentic
               34:30 - This boiler? - Yes
               34:44 I am not forcing you to buy this boiler…
               34:52 Who will give her a one liter stainless steel boiler for one Lari?
               34:54 Glass boilers cost two

    Search and open file

        library captions fts.db 'two words' --open
""",
}


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=USAGE['search'])

    arggroups.sql_fs(parser)

    arggroups.playback(parser)
    arggroups.post_actions(parser)

    parser.set_defaults(sort=["path", "time"])

    parser.add_argument("--open", "--play", action="store_true")
    parser.add_argument("--overlap", type=int, default=8)
    parser.add_argument("--table", action="store_true")

    parser.set_defaults(print="p")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search_captions", nargs="*")
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    arggroups.playback_post(args)
    arggroups.post_actions_post(args)

    return args


def printer(args, captions) -> None:
    captions = iterables.list_dict_filter_bool(captions)
    if not captions:
        processes.no_media_found()

    tbl = deepcopy(captions)
    printing.col_hhmmss(tbl, "time")

    if args.print == "p":
        print(f"{len(captions)} captions")
        for path, path_group in groupby(tbl, key=lambda x: x["path"]):
            path_group = list(path_group)
            title = path_group[0].get("title")
            print(" - ".join(iterables.concat(title, path)))
            for caption in path_group:
                for line in textwrap.wrap(caption["text"], subsequent_indent=" " * 9, initial_indent=f"{caption['time']} ", width=consts.TERMINAL_SIZE.columns - 2):  # type: ignore
                    print(line)
            print()
    else:
        media_printer.media_printer(args, captions, units="captions")


def merge_captions(args, captions):
    def get_end(caption):
        return caption["time"] + (len(caption["text"]) / 4.2 / 220 * 60)

    merged_captions = []
    for path, group in groupby(
        captions,
        key=lambda x: x["path"],
    ):  # group by only does contiguous items with the same key
        group = list(group)
        merged_group = {
            **group[0],
            "path": path,
            "end": get_end(group[0]),
        }  # type: ignore
        for i in range(1, len(group)):
            end = get_end(group[i])

            if (
                abs(group[i]["time"] - merged_group["end"]) <= args.overlap  # type: ignore
                or abs(group[i]["time"] - merged_group["time"]) <= args.overlap  # type: ignore
            ):
                merged_group["end"] = end
                if group[i]["text"] not in merged_group["text"]:  # type: ignore
                    merged_group["text"] += ". " + group[i]["text"]  # type: ignore
            else:
                merged_captions.append(merged_group)
                merged_group = {
                    "path": path,
                    "time": group[i]["time"],  # type: ignore
                    "end": end,
                    "text": group[i]["text"],  # type: ignore
                }
        merged_captions.append(merged_group)

    return merged_captions


def search() -> None:
    args = parse_args()
    query, bindings = construct_captions_search_query(args)
    captions = list(args.db.query(query, bindings))
    merged_captions = merge_captions(args, captions)

    if args.open:
        pl = media_player.MediaPrefetcher(args, merged_captions)
        pl.fetch()
        while pl.remaining:
            d = pl.get_m()
            if d:
                print(d["text"])
                m = args.db.pop_dict("select * from media where path = ?", [d["path"]])
                m["player"].extend([f'--start={d["time"] - 2}', f'--end={int(d["end"] + 1.5)}'])
                r = media_player.single_player(args, m)
                if r.returncode != 0:
                    log.warning("Player exited with code %s", r.returncode)
                    if args.ignore_errors:
                        return
                    else:
                        raise SystemExit(r.returncode)
    else:
        printer(args, merged_captions)
