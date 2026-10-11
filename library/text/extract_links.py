import json
from collections import deque
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from library import usage
from library.data.http_errors import HTTPStatus
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    devices,
    iterables,
    path_utils,
    printing,
    shell_utils,
    strings,
    web,
)
from library.utils.log_utils import log
import pathlib


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.extract_links)
    arggroups.extractor(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)
    arggroups.spider(parser)

    parser.add_argument("--download", action="store_true", help="Download filtered links")
    arggroups.download(parser)
    parser.set_defaults(profile=consts.DBType.filesystem)

    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.extractor_post(args)
    arggroups.filter_links_post(args)
    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)

    return args


def is_desired_url(args, link, link_text, before, after) -> bool:
    case_sensitive = args.case_sensitive

    def include_match(patterns, text) -> bool:
        if args.strict_include:
            return strings.glob_match_all(patterns, [text], case_sensitive)
        return strings.glob_match_any(patterns, [text], case_sensitive)

    def exclude_match(patterns, text) -> bool:
        if args.strict_exclude:
            return strings.glob_match_all(patterns, [text], case_sensitive)
        return strings.glob_match_any(patterns, [text], case_sensitive)

    link_match = link if case_sensitive else link.lower()
    link_text_match = link_text if case_sensitive else link_text.lower()

    if args.path_include and not include_match(args.path_include, link_match):
        log.debug("no match path-include: %s", link_match)
        return False
    if args.path_exclude and exclude_match(args.path_exclude, link_match):
        log.debug("matched path-exclude: %s", link_match)
        return False

    if args.text_exclude and exclude_match(args.text_exclude, link_text_match):
        log.debug("matched text-exclude: %s", link_text_match)
        return False
    if args.text_include and not include_match(args.text_include, link_text_match):
        log.debug("no match text-include: %s", link_text_match)
        return False

    if args.before_exclude or args.before_include:
        if args.before_include and not before:
            return False

        before_match = before if case_sensitive else before.lower()

        if args.before_exclude and exclude_match(args.before_exclude, before_match):
            log.debug("matched before-exclude: %s", before_match)
            return False
        if args.before_include and not include_match(args.before_include, before_match):
            log.debug("no match before-include: %s", before_match)
            return False

        if args.before_exclude or args.before_include:  # just logging
            log.info("  before: %s", before_match)

    if args.after_exclude or args.after_include:
        if args.after_include and not after:
            return False

        after_match = after if case_sensitive else after.lower()

        if args.after_exclude and exclude_match(args.after_exclude, after_match):
            log.debug("matched after-exclude: %s", after_match)
            return False
        if args.after_include and not include_match(args.after_include, after_match):
            log.debug("no match after-include: %s", after_match)
            return False

        if args.after_exclude or args.after_include:  # just logging
            log.info("  after: %s", after_match)

    if args.text_exclude or args.text_include:  # just logging
        log.info("  text: `%s`", link_text_match.strip())

    return True


def get_highest_res(srcset):
    if not srcset:
        return None
    try:
        parts = [s.strip().split() for s in srcset.split(",")]
        clean_parts = [p for p in parts if len(p) == 2]
        if not clean_parts:
            return srcset.strip().split()[0] if srcset else None

        highest = max(clean_parts, key=lambda x: int(x[1].lower().replace("w", "").replace("x", "")))
        return highest[0]
    except (ValueError, IndexError):
        return None


def parse_inner_urls(args, base_url, markup):
    from bs4 import BeautifulSoup

    if base_url.endswith(".xml"):
        soup = BeautifulSoup(markup, "xml")
    else:
        soup = BeautifulSoup(markup, "lxml")

    stop_texts = getattr(args, "stop_text", None) or []
    for stop_text in stop_texts:
        if soup.find(string=lambda s: stop_text in s):
            return None

    if base_url.startswith("//"):
        base_url = "https:" + base_url

    # RFC 3986 is not enough... (mod_rewrite et al.)
    base_tag = soup.find("base")
    if base_tag:
        base_href = base_tag.get("href")  # type: ignore
        if base_href:
            base_url = urljoin(base_url, base_href)  # type: ignore

    link_attrs = set()
    if args.href:
        link_attrs.add("href")
    if args.src:
        link_attrs.add("src")
    if args.url:
        link_attrs.add("url")
    if args.data_src:
        link_attrs.update({"data-src", "data-url", "data-original"})

    image_attrs = set()
    if args.srcset:
        image_attrs.add("srcset")
    if args.data_srcset:
        image_attrs.add("data-srcset")

    url_renames = args.url_renames.items()

    def delimit_fn(el):
        return any(el.has_attr(s) for s in link_attrs | image_attrs)

    tags = web.tags_with_text(soup, delimit_fn)
    for tag in tags:
        for attr_name, attr_value in tag.attrs.items():
            link = None

            if attr_name in link_attrs:
                link = str(attr_value).strip()
            elif attr_name in image_attrs:
                link = get_highest_res(str(attr_value))

            if not link or link.startswith("#"):
                continue

            link = web.construct_absolute_url(base_url, link)
            link_text = strings.remove_consecutive_whitespace(tag.text.strip())

            if is_desired_url(args, link, link_text, tag.before_text, tag.after_text):
                for k, v in url_renames:
                    link = link.replace(k, v)

                yield {
                    "link": link,
                    "link_text": strings.strip_enclosing_quotes(link_text),
                    "before_text": tag.before_text,
                    "after_text": tag.after_text,
                }


def get_inner_urls(args, url):
    log.debug("Loading links from %s", url)

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
        if args.local_html:
            local_path = url.removeprefix("file://")
            markup = pathlib.Path(unquote(local_path)).read_text()
            url = "file://" + local_path
        else:
            try:
                r = web.session.get(url, timeout=120)
            except Exception as excinfo:
                if "too many 429 error" in str(excinfo):
                    raise
                log.exception("Could not get a valid response from the server")
                return None
            if r.status_code == HTTPStatus.NOT_FOUND:
                log.warning("404 Not Found Error: %s", url)
                is_error = True
            else:
                r.raise_for_status()
            markup = r.content

        yield from parse_inner_urls(args, url, markup)

    web.sleep(args)

    if is_error:
        return None


def url_parent_prefix(url: str) -> str:
    """Return scheme://netloc/parent/ for a seed URL (dropping the final file segment)."""
    parsed = urlparse(url)
    path = parsed.path
    if not path.endswith("/"):
        path = path.rsplit("/", 1)[0] + "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def is_within_parent(parent_prefix: str, link: str) -> bool:
    parent = urlparse(parent_prefix)
    child = urlparse(urldefrag(link)[0])
    # Ignore scheme so http->https redirects within the same host are still followed
    return child.netloc == parent.netloc and child.path.startswith(parent.path)


def crawl(args, seeds):
    """Yield filtered link dicts reachable from seeds, spidering only within each seed's parent directory.

    Links pointing outside the seed domain/parent are still yielded (so they can be
    downloaded) but are not followed.
    """
    prefixes = [url_parent_prefix(seed) for seed in seeds]
    queue = deque(seeds)
    spidered = set()
    yielded = set()

    while queue:
        url = queue.popleft()
        url_key = urldefrag(url)[0]
        if url_key in spidered:
            continue
        spidered.add(url_key)

        for d in get_inner_urls(args, url):
            link = d["link"]
            link_key = urldefrag(link)[0]

            if link_key not in yielded:
                yielded.add(link_key)
                yield d

            if (
                link_key not in spidered
                and any(is_within_parent(prefix, link) for prefix in prefixes)
                and (args.local_html or web.is_html(args, link))
            ):
                queue.append(link)


def print_or_download(args, d):
    url = d["link"]
    if args.download:
        try:
            web.download_link(args, url)
        except RuntimeError as excinfo:
            log.error("[%s]: %s", url, excinfo)
    else:
        if not args.no_url_decode:
            url = path_utils.url_decode(url).strip()
        if args.verbose >= consts.LOG_DEBUG:
            printing.pipe_print(json.dumps(d, ensure_ascii=False))
        else:
            printing.pipe_print(url)


def extract_links() -> None:
    args = parse_args()

    if args.no_extract:
        for url in shell_utils.gen_paths(args):
            if args.url_encode:
                url = web.url_encode(url).strip()
            if args.download:
                try:
                    web.download_link(args, url)
                except RuntimeError as excinfo:
                    log.error("[%s]: %s", url, excinfo)
            else:
                printing.pipe_print(url)
        return

    if args.selenium:
        web.load_selenium(args)
    try:
        if args.recursive:
            for d in crawl(args, list(shell_utils.gen_paths(args))):
                print_or_download(args, d)
        else:
            for url in shell_utils.gen_paths(args):
                for d in iterables.return_unique(get_inner_urls, lambda d: d["link"])(args, url):
                    print_or_download(args, d)

    finally:
        if args.selenium:
            web.quit_selenium(args)
