#!/usr/bin/python3
import re, urllib.parse

from library import usage
from library.utils import arggroups, argparse_utils, devices
from library.utils.log_utils import log


def parse_args(args):
    parser = argparse_utils.ArgumentParser(usage=usage.expand_links)
    parser.add_argument(
        "--search-urls", "-s", action="append", required=True, help='List of search URLs with a placeholder "%s".'
    )
    parser.add_argument("--browser", nargs="?", const="default")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


def expand_links(args=None):
    args = parse_args(args)

    links = []
    for query in args.paths:
        for search_url in args.search_urls:
            words = re.findall(r"\w+", query)
            log.debug("words: %s", words)
            words = [word for word in words if word]
            encoded_query = urllib.parse.quote(" ".join(words))

            if "%s" not in search_url:
                raise SystemExit(f"Error: No '%s' in provided search_url '{search_url}'")

            links.append(search_url.replace("%s", encoded_query))

    devices.browse(args.browser, links)
