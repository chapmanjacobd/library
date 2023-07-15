import argparse, os
from pathlib import Path
from typing import Dict, List

import humanize

from xklb import consts, db, player, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library disk_usage",
        usage=usage.disk_usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--sort-by", "--sort", "-u")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="4000")
    parser.add_argument(
        "--size",
        "-S",
        action="append",
        help="Only include files of specific sizes (uses the same syntax as fd-find)",
    )
    parser.add_argument("--depth", "-d", default=0, type=int, help="Depth of folders")
    parser.add_argument("--include", "-s", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)

    parser.add_argument("--tui", "-tui", action="store_true")
    parser.add_argument("--print", "-p", default="", const="p", nargs="?")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("working_directory", nargs="*", default=os.sep)
    args = parser.parse_intermixed_args()
    args.db = db.connect(args)

    args.include += args.working_directory
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if args.size:
        args.size = utils.parse_human_to_sql(utils.human_to_bytes, "size", args.size)

    args.action = consts.SC.diskusage
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def sort_by(args):
    if args.sort_by:
        return lambda x: x.get(args.sort_by)

    return lambda x: (x["size"] / (x.get("count") or 1), x["size"], x.get("count") or 1)


def get_subset(args, level=None, prefix=None) -> List[Dict]:
    d = {}
    excluded_files = set()

    for m in args.data:
        if prefix is not None and not m["path"].startswith(prefix):
            continue

        p = m["path"].split(os.sep)
        if level is not None and len(p) == level and not m["path"].endswith(os.sep):
            d[m["path"]] = m

        while len(p) >= 2:
            p.pop()
            if p == [""]:
                continue

            parent = os.sep.join(p) + os.sep
            if level is not None and len(p) != level:
                excluded_files.add(parent)

            if parent not in d:
                d[parent] = {"size": 0, "count": 0}
            d[parent]["size"] += m.get("size", 0)
            d[parent]["count"] += 1

    reverse = True
    if args.sort_by and " desc" in args.sort_by:
        args.sort_by = args.sort_by.replace(" desc", "")
        reverse = False

    return sorted(
        [{"path": k, **v} for k, v in d.items() if k not in excluded_files],
        key=sort_by(args),
        reverse=reverse,
    )


def load_subset(args):
    level = args.depth
    if args.depth == 0:
        while len(args.subset) < 2:
            level += 1
            args.subset = get_subset(args, level=level, prefix=args.cwd)
    else:
        args.subset = get_subset(args, level=level, prefix=args.cwd)

    if not args.subset:
        utils.no_media_found()

    args.cwd = os.sep.join(args.subset[0]["path"].split(os.sep)[: level - 1]) + os.sep
    return args.cwd, args.subset


def get_data(args) -> List[dict]:
    m_columns = db.columns(args, "media")
    args.filter_sql = []
    args.filter_bindings = {}

    if args.size:
        args.filter_sql.append(" and size IS NOT NULL " + args.size)
    db.construct_search_bindings(args, m_columns)

    media = list(
        args.db.query(
            f"""
        SELECT
            path
            , size
        FROM media m
        WHERE 1=1
            and size > 0
            {'and coalesce(time_deleted, 0) = 0' if 'time_deleted' in m_columns else ''}
            {'and coalesce(is_dir, 0) = 0' if 'is_dir' in m_columns else ''}
            {" ".join(args.filter_sql)}
        ORDER BY path
        """,
            args.filter_bindings,
        ),
    )

    if not media:
        utils.no_media_found()
    return media


def run_tui(args):
    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll
    from textual.reactive import var
    from textual.widgets import Footer, Label, OptionList

    class DiskUsage(App):
        CSS = """
        Screen {
            opacity: 0%;
        }

        Label {
            text-style: reverse;
        }

        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("Left", "pop", "Go up"),
        ]

        def __init__(self, args):
            super().__init__()
            self.args = args
            self.dark = False
            var(self.args.subset, always_update=True)

        @staticmethod
        def _path(cwd, d):
            file_count = ""
            if d.get("count"):
                file_count = str(d["count"]) + " files"

            return "\t".join([d["path"].replace(cwd, ""), humanize.naturalsize(d["size"]), file_count])

        def compose(self) -> ComposeResult:
            yield Label("Disk Usage ~ Use the arrow keys to navigate")
            yield Label(f"--- {args.cwd} ---", id="cwd")
            yield VerticalScroll(OptionList(*[self._path(args.cwd, d) for d in self.args.subset]))
            yield Label(
                f"Total disk usage: {humanize.naturalsize(sum(d['size'] for d in self.args.subset))}  Items: {sum(d.get('count') or 1 for d in self.args.subset)}",
            )
            yield Footer()

        def on_mount(self) -> None:
            self.query_one(OptionList).focus()
            # self.call_later(self.load_directory, self.root)

        def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
            m = self.args.subset[event.option_index]
            if m.get("count"):
                self.args.cwd = m["path"]
                cwd, subset = load_subset(self.args)
                self.query_one(OptionList).clear_options()
                self.query_one(OptionList).add_options([self._path(cwd, d) for d in subset])
                self.query_one(OptionList).refresh()

            self.refresh()

        def action_pop(self) -> None:
            self.args.cwd.pop()
            load_subset(self.args)
            self.refresh()

    DiskUsage(args).run()


def disk_usage():
    args = parse_args()
    args.data = get_data(args)
    args.subset = []
    args.cwd = None

    load_subset(args)

    if args.tui:
        run_tui(args)
    else:
        player.media_printer(args, args.subset, units="files / folders")


if __name__ == "__main__":
    disk_usage()
