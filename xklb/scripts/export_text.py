import argparse
from pathlib import Path

from xklb import usage
from xklb.utils import db_utils, objects
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library export-text", usage=usage.export_text)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--format", default="html")
    parser.add_argument("database")
    args = parser.parse_args()

    Path(args.database).touch()
    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def media_to_files(args):
    if args.format != "html":
        raise NotImplementedError

    media = list(args.db.query("SELECT * FROM media"))
    for d in media:
        path = d.pop("path")
        title = d.pop("title", None) or path

        lines = ["<html><body>", path, "<br>", title, "<br>"]

        for key in ["subtitle", "author", "artist", "time_created", "duration", "text", *list(d.keys())]:
            value = d.pop(key, None)
            if value:
                lines.append(f"{key}: {value}")
                lines.append("<br>")

        lines.append("</body></html>")

        with open(f"{title}.html", "w") as f:
            f.writelines(lines)


def export_text():
    args = parse_args()
    media_to_files(args)


if __name__ == "__main__":
    export_text()
