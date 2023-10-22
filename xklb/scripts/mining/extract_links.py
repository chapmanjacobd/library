import argparse, time

from xklb import usage
from xklb.utils import printing, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(
        prog="library extract-links",
        usage=usage.extract_links,
    )
    parser.add_argument(
        "--path-include",
        "--include",
        "-s",
        nargs="*",
        default=[],
        help="path substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--text-include", nargs="*", default=[], help="link text substrings for inclusion (all must match to include)"
    )
    parser.add_argument(
        "--after-include",
        nargs="*",
        default=[],
        help="plain text substrings after URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--before-include",
        nargs="*",
        default=[],
        help="plain text substrings before URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--path-exclude",
        "--exclude",
        "-E",
        nargs="*",
        default=["javascript:", "mailto:", "tel:"],
        help="path substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--text-exclude",
        nargs="*",
        default=[],
        help="link text substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--after-exclude",
        nargs="*",
        default=[],
        help="plain text substrings after URL for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--before-exclude",
        nargs="*",
        default=[],
        help="plain text substrings before URL for exclusion (any must match to exclude)",
    )
    parser.add_argument("--strict-include", action="store_true", help="All include args must resolve true")
    parser.add_argument("--strict-exclude", action="store_true", help="All exclude args must resolve true")
    parser.add_argument("--case-sensitive", action="store_true", help="Filter with case sensitivity")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--download", action="store_true", help="Download filtered links")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument("--file", "-f", help="File with one URL per line")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    if not args.case_sensitive:
        args.before_include = [s.lower() for s in args.before_include]
        args.path_include = [s.lower() for s in args.path_include]
        args.text_include = [s.lower() for s in args.text_include]
        args.after_include = [s.lower() for s in args.after_include]
        args.before_exclude = [s.lower() for s in args.before_exclude]
        args.path_exclude = [s.lower() for s in args.path_exclude]
        args.text_exclude = [s.lower() for s in args.text_exclude]
        args.after_exclude = [s.lower() for s in args.after_exclude]

    return args


def construct_absolute_url(url, href):
    from urllib.parse import urlparse

    up = urlparse(href)
    if not up.netloc:
        up = urlparse(url)
        href = up.scheme + "://" + up.netloc + href
    return href


def is_desired_url(args, a_element, href) -> bool:
    path = href if args.case_sensitive else href.lower()

    include_cond = all if args.strict_include else any
    exclude_cond = all if args.strict_exclude else any

    if args.path_include and not include_cond(inc in path for inc in args.path_include):
        log.debug("path-include: %s", path)
        return False
    if args.path_exclude and exclude_cond(ex in path for ex in args.path_exclude):
        log.debug("path-exclude: %s", path)
        return False

    link_text = a_element.text if args.case_sensitive else a_element.text.lower()

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
        log.info("  text: %s", link_text)

    return True


def get_inner_urls(args, url, markup):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(markup, "html.parser")
    inner_urls = set()

    for a in soup.findAll("a", attrs={"href": True}):
        log.debug(a)

        href = a["href"].strip()
        if (len(href) > 1) and href[0] != "#":
            href = construct_absolute_url(url, href)
            if is_desired_url(args, a, href):
                inner_urls.add(href)

        # breakpoint()

    return inner_urls


def get_page_infinite_scroll(driver, url):
    driver.get(url)
    time.sleep(1)

    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    return driver.page_source


def from_url(args, line):
    url = line.rstrip("\n")
    if url in ["", '""', "\n"]:
        return None

    if args.local_html:
        with open(url, "r") as f:
            markup = f.read()
        url = "file://" + url
    elif args.scroll:
        markup = get_page_infinite_scroll(args.driver, url)
    else:
        r = web.requests_session().get(url, timeout=120, headers=web.headers)
        r.raise_for_status()
        markup = r.content

    inner_urls = get_inner_urls(args, url, markup)

    return inner_urls


def print_or_download(args, found_urls):
    if args.download:
        for inner_url in found_urls:
            web.download_url(inner_url)
    else:
        printing.pipe_print("\n".join(found_urls))


def extract_links() -> None:
    args = parse_args()

    if args.scroll:
        web.load_selenium(args)

    if args.file:
        with open(args.file) as f:
            for line in f:
                found_urls = from_url(args, line)
                print_or_download(args, found_urls)
    else:
        for path in args.paths:
            found_urls = from_url(args, path)
            print_or_download(args, found_urls)

    if args.scroll:
        args.driver.quit()


if __name__ == "__main__":
    # echo $directors | python scripts/mining/nfb.ca.py | tee -a ~/.jobs/75
    extract_links()
