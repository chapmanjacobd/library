import argparse

from library import usage
from library.utils import arggroups, argparse_utils


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.export_text)
    parser.add_argument("--format", default="html")
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_args()

    arggroups.args_post(args, parser, create_db=True)
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
