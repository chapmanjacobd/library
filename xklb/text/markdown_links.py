from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils, web

COMMON_SITE_TITLE_SUFFIXES = [
    " | Listen online for free on SoundCloud",
    " - YouTube",
]


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.markdown_links)
    arggroups.requests(parser)
    parser.add_argument("--local-html", action="store_true", help="Treat paths as Local HTML files")
    arggroups.selenium(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)

    return args


def markdown_links():
    args = parse_args()

    if args.selenium:
        web.load_selenium(args)
    try:
        for url in arg_utils.gen_paths(args):
            title = web.get_title(args, url)

            if title.startswith("Stream ") and "SoundCloud" in title:
                title = title.replace("Stream ", "", 1)

            for x in COMMON_SITE_TITLE_SUFFIXES:
                title = title.replace(x, "")

            text = f"[{title}]({url})"
            if len(args.paths) > 1:
                print(f"- {text}")
            else:
                print(text)
    finally:
        if args.selenium:
            web.quit_selenium(args)


if __name__ == "__main__":
    markdown_links()
