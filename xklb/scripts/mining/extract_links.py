import argparse

from xklb import usage
from xklb.utils import arg_utils, consts, devices, iterables, printing, strings, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(
        prog="library extract-links",
        usage=usage.extract_links,
    )
    parser.add_argument(
        "--path-include",
        "--include-path",
        "--include",
        "-s",
        nargs="*",
        default=[],
        help="path substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--text-include",
        "--include-text",
        nargs="*",
        default=[],
        help="link text substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--after-include",
        "--include-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--before-include",
        "--include-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--path-exclude",
        "--exclude-path",
        "--exclude",
        "-E",
        nargs="*",
        default=["javascript:", "mailto:", "tel:"],
        help="path substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--text-exclude",
        "--exclude-text",
        nargs="*",
        default=[],
        help="link text substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--after-exclude",
        "--exclude-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--before-exclude",
        "--exclude-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for exclusion (any must match to exclude)",
    )

    parser.add_argument("--strict-include", action="store_true", help="All include args must resolve true")
    parser.add_argument("--strict-exclude", action="store_true", help="All exclude args must resolve true")
    parser.add_argument("--case-sensitive", action="store_true", help="Filter with case sensitivity")
    parser.add_argument(
        "--no-url-decode",
        "--skip-url-decode",
        action="store_true",
        help="Skip URL-decode for --path-include/--path-exclude",
    )

    parser.add_argument("--print-link-text", "--print-title", action="store_true")
    parser.add_argument("--cookies", help="path to a Netscape formatted cookies file")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]")
    parser.add_argument("--selenium", action="store_true")
    parser.add_argument("--manual", action="store_true", help="Confirm manually in shell before exiting the browser")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--auto-pager", "--autopager", action="store_true")
    parser.add_argument("--poke", action="store_true")
    parser.add_argument("--chrome", action="store_true")
    parser.add_argument("--download", action="store_true", help="Download filtered links")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("--no-extract", "--skip-extract", action="store_true")
    parser.add_argument("--local-file", "--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument("--file", "-f", help="File with one URL per line")

    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    if args.scroll:
        args.selenium = True

    if not args.case_sensitive:
        args.before_include = [s.lower() for s in args.before_include]
        args.path_include = [s.lower() for s in args.path_include]
        args.text_include = [s.lower() for s in args.text_include]
        args.after_include = [s.lower() for s in args.after_include]
        args.before_exclude = [s.lower() for s in args.before_exclude]
        args.path_exclude = [s.lower() for s in args.path_exclude]
        args.text_exclude = [s.lower() for s in args.text_exclude]
        args.after_exclude = [s.lower() for s in args.after_exclude]

    if not args.no_url_decode:
        args.path_include = [web.url_decode(s) for s in args.path_include]
        args.path_exclude = [web.url_decode(s) for s in args.path_exclude]

    return args


def is_desired_url(args, a_element, link, link_text) -> bool:
    include_cond = all if args.strict_include else any
    exclude_cond = all if args.strict_exclude else any

    if args.path_include and not include_cond(inc in link for inc in args.path_include):
        log.debug("path-include: %s", link)
        return False
    if args.path_exclude and exclude_cond(ex in link for ex in args.path_exclude):
        log.debug("path-exclude: %s", link)
        return False

    if args.text_exclude and exclude_cond(ex in link_text for ex in args.text_exclude):
        log.debug("text-exclude: %s", link_text)
        return False
    if args.text_include and not include_cond(inc in link_text for inc in args.text_include):
        log.debug("text-include: %s", link_text)
        return False

    if args.before_exclude or args.before_include or args.after_exclude or args.after_include:
        before, after = web.extract_nearby_text(a_element)
        before_text = before if args.case_sensitive else before.lower()
        after_text = after if args.case_sensitive else after.lower()

        if args.before_exclude and exclude_cond(ex in before_text for ex in args.before_exclude):
            log.debug("before-exclude: %s", before_text)
            return False
        if args.after_exclude and exclude_cond(ex in after_text for ex in args.after_exclude):
            log.debug("after-exclude: %s", after_text)
            return False
        if args.before_include and not include_cond(inc in before_text for inc in args.before_include):
            log.debug("before-include: %s", before_text)
            return False
        if args.after_include and not include_cond(inc in after_text for inc in args.after_include):
            log.debug("after-include: %s", after_text)
            return False

        if args.before_exclude or args.before_include:
            log.info("  before: %s", before_text)
        if args.after_exclude or args.after_include:
            log.info("  after: %s", after_text)

    if args.text_exclude or args.text_include:
        log.info("  text: `%s`", link_text.strip())

    return True


def parse_inner_urls(args, url, markup):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(markup, "html.parser")

    for a_ref in soup.findAll(href=True):
        log.debug(a_ref)

        href = a_ref["href"].strip()
        if (len(href) > 1) and href[0] != "#":
            link = web.construct_absolute_url(url, href).strip()
            link_text = strings.remove_consecutive_whitespace(a_ref.text.strip())

            link_lower = link if args.case_sensitive else link.lower()
            link_text_lower = link_text if args.case_sensitive else link_text.lower()

            if is_desired_url(args, a_ref, link_lower, link_text_lower):
                yield (link, strings.strip_enclosing_quotes(link_text))

        if args.verbose > consts.LOG_DEBUG_SQL:
            breakpoint()


def get_inner_urls(args, url):
    is_error = False
    if args.selenium:
        web.selenium_get_page(args, url)

        if args.manual:
            while devices.confirm("Extract HTML from browser?"):
                markup = web.selenium_extract_html(args.driver)
                yield from parse_inner_urls(args, url, markup)
        else:
            for markup in web.infinite_scroll(args.driver):
                yield from parse_inner_urls(args, url, markup)
    else:
        if args.local_file:
            with open(url, "r") as f:
                markup = f.read()
            url = "file://" + url
        else:
            r = web.requests_session(args).get(url, timeout=120)
            if r.status_code == 404:
                log.warning("404 Not Found Error: %s", url)
                is_error = True
            else:
                r.raise_for_status()
            markup = r.content

        yield from parse_inner_urls(args, url, markup)

    if is_error:
        yield None


def print_or_download(args, a_ref):
    link, link_text = a_ref
    if args.download:
        web.download_url(link)
    else:
        if args.print_link_text:
            printing.pipe_print(f"{link}\t{link_text}")
        else:
            printing.pipe_print(link)


def extract_links() -> None:
    args = parse_args()

    if args.no_extract:
        for url in arg_utils.gen_paths(args):
            url = web.url_decode(url).strip()
            if args.download:
                web.download_url(url)
            else:
                printing.pipe_print(url)
        return

    if args.selenium:
        web.load_selenium(args)
    try:
        for url in arg_utils.gen_paths(args):
            for a_ref in iterables.return_unique(get_inner_urls)(args, url):
                if a_ref is None:
                    break

                print_or_download(args, a_ref)

    finally:
        if args.selenium:
            web.quit_selenium(args)


if __name__ == "__main__":
    extract_links()
