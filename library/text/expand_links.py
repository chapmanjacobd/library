#!/usr/bin/python3
import re, urllib.parse

from library.utils import arggroups, argparse_utils, devices
from library.utils.log_utils import log

USAGE = {
    'expand_links': """library text expand links SEARCH_URLS QUERY ...

    Expand search URLs with multiple queries

        library text expand links -s https://www.google.com/search?q=%s -s https://duckduckgo.com/?q=%s library
        https://www.google.com/search?q=library
        https://duckduckgo.com/?q=library

        library text expand links -s https://www.walmart.com/search?q=%s -s https://www.target.com/s?searchTerm=%s "Dr. Pepper" pepcidine
        https://www.walmart.com/search?q=Dr%20Pepper
        https://www.target.com/s?searchTerm=Dr%20Pepper
        https://www.walmart.com/search?q=pepcidine
        https://www.target.com/s?searchTerm=pepcidine

    Open in browser

        library text expand links ... --browser
        library text expand links ... --browser chrome

""",
}


def parse_args(args):
    parser = argparse_utils.ArgumentParser(usage=USAGE['expand_links'])
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
                msg = f"Error: No '%s' in provided search_url '{search_url}'"
                raise SystemExit(msg)

            links.append(search_url.replace("%s", encoded_query))

    devices.browse(args.browser, links)
