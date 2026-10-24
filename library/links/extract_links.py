import json, pathlib, sys
from collections import deque
from urllib.parse import unquote, urldefrag, urljoin, urlparse

import requests

from library import usage as usage_mod
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

SRCSET_PARTS = 2


def _base_parser(usage):
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.extractor(parser, no_extract=False)
    arggroups.requests(parser)
    return parser


def _add_link_extraction(parser):
    arggroups.selenium(parser)
    arggroups.filter_links(parser)
    arggroups.spider(parser)


def _post_link_extraction(args):
    arggroups.filter_links_post(args)
    web.requests_session(args)
    arggroups.selenium_post(args)


def parse_args_extract():
    parser = _base_parser(usage_mod.extract_links)
    _add_link_extraction(parser)
    parser.set_defaults(download=False, direct=False)

    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.extractor_post(args)
    _post_link_extraction(args)
    return args


def _matches_link_patterns(args, text, include, exclude, label, case_sensitive):
    if include:
        included = (
            strings.glob_match_all(include, [text], case_sensitive)
            if args.strict_include
            else strings.glob_match_any(include, [text], case_sensitive)
        )
        if not included:
            log.debug("no match %s-include: %s", label, text)
            return False
    if exclude:
        excluded = (
            strings.glob_match_all(exclude, [text], case_sensitive)
            if args.strict_exclude
            else strings.glob_match_any(exclude, [text], case_sensitive)
        )
        if excluded:
            log.debug("matched %s-exclude: %s", label, text)
            return False
    return True


def _matches_context(args, text, include, exclude, label, case_sensitive):
    if not include and not exclude:
        return True
    if include and not text:
        return False
    context = text if case_sensitive else text.lower()
    if not _matches_link_patterns(args, context, include, exclude, label, case_sensitive):
        return False
    log.info("  %s: %s", label, context)
    return True


def is_desired_url(args, link, link_text, before, after) -> bool:
    case_sensitive = args.case_sensitive
    link_match = link if case_sensitive else link.lower()
    link_text_match = link_text if case_sensitive else link_text.lower()
    if not _matches_link_patterns(args, link_match, args.path_include, args.path_exclude, "path", case_sensitive):
        return False
    if not _matches_link_patterns(args, link_text_match, args.text_include, args.text_exclude, "text", case_sensitive):
        return False
    if not _matches_context(args, before, args.before_include, args.before_exclude, "before", case_sensitive):
        return False
    if not _matches_context(args, after, args.after_include, args.after_exclude, "after", case_sensitive):
        return False
    if args.text_exclude or args.text_include:
        log.info("  text: `%s`", link_text_match.strip())
    return True


def get_highest_res(srcset):
    if not srcset:
        return None
    try:
        parts = [s.strip().split() for s in srcset.split(",")]
        clean_parts = [p for p in parts if len(p) == SRCSET_PARTS]
        if not clean_parts:
            return srcset.strip().split()[0] if srcset else None

        highest = max(clean_parts, key=lambda x: int(x[1].lower().replace("w", "").replace("x", "")))
        return highest[0]
    except (ValueError, IndexError):
        return None


def _link_attributes(args):
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
    return link_attrs, image_attrs


def _iter_tag_links(args, base_url, tags, link_attrs, image_attrs, url_renames):
    for tag in tags:
        for attr_name, attr_value in tag.attrs.items():
            if attr_name in link_attrs:
                link = str(attr_value).strip()
            elif attr_name in image_attrs:
                link = get_highest_res(str(attr_value))
            else:
                continue
            if not link or link.startswith("#"):
                continue

            link = web.construct_absolute_url(base_url, link)
            link_text = strings.remove_consecutive_whitespace(tag.text.strip())
            if not is_desired_url(args, link, link_text, tag.before_text, tag.after_text):
                continue
            for key, value in url_renames:
                link = link.replace(key, value)
            yield {
                "link": link,
                "link_text": strings.strip_enclosing_quotes(link_text),
                "before_text": tag.before_text,
                "after_text": tag.after_text,
            }


def parse_inner_urls(args, base_url, markup):
    from bs4 import BeautifulSoup

    if base_url.endswith(".xml"):
        soup = BeautifulSoup(markup, "xml")
    else:
        soup = BeautifulSoup(markup, "lxml")

    stop_texts = getattr(args, "stop_text", None) or []
    if any(
        soup.find(string=lambda s, stop_text=stop_text: isinstance(s, str) and stop_text in s)
        for stop_text in stop_texts
    ):
        return None

    if base_url.startswith("//"):
        base_url = "https:" + base_url

    # RFC 3986 is not enough... (mod_rewrite et al.)
    base_tag = soup.find("base")
    if base_tag:
        base_href = base_tag.get("href")  # type: ignore
        if base_href:
            base_url = urljoin(base_url, base_href)  # type: ignore

    link_attrs, image_attrs = _link_attributes(args)
    url_renames = args.url_renames.items()

    def delimit_fn(el):
        return any(el.has_attr(s) for s in link_attrs | image_attrs)

    tags = web.tags_with_text(soup, delimit_fn)
    yield from _iter_tag_links(args, base_url, tags, link_attrs, image_attrs, url_renames)


def _load_remote_markup(url):
    fetch_url = web.wayback_replay_url(url) if web.is_wayback_url(url) else url
    try:
        response = web.session.get(fetch_url, timeout=120)
    except Exception as excinfo:
        if "too many 429 error" in str(excinfo):
            raise
        log.exception("Could not get a valid response from the server")
        return None, False
    if response.status_code == HTTPStatus.NOT_FOUND:
        log.warning("404 Not Found Error: %s", url)
        return response.content, True
    response.raise_for_status()
    return response.content, False


def _load_markup(args, url):
    if args.local_html:
        local_path = url.removeprefix("file://")
        return pathlib.Path(unquote(local_path)).read_text(), "file://" + local_path, False
    markup, is_error = _load_remote_markup(url)
    return markup, url, is_error


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
        markup, url, is_error = _load_markup(args, url)
        if markup is None:
            return None
        yield from parse_inner_urls(args, url, markup)
    web.sleep(args)
    if is_error:
        return None


def cdx_query(url: str) -> str:
    """Return the CDX query for a seed: its domain and parent directory."""
    parsed = urlparse(web.wayback_normalize(url))
    path = parsed.path
    if not path.endswith("/"):
        path = path.rsplit("/", 1)[0] + "/"
    return f"{parsed.netloc}{path}*"


def get_cdx_urls(args, url):
    """Yield archived captures under a seed's domain/parent from a CDX index (--webcache)."""
    cdx_toolkit = web.load_cdx_toolkit()

    source = args.webcache_source
    query = cdx_query(url)
    log.info("Querying CDX (%s): %s", source, query)

    fetcher = cdx_toolkit.CDXFetcher(source=source)
    kwargs = {"limit": args.webcache_limit}
    if args.webcache_from:
        kwargs["from_ts"] = args.webcache_from
    if args.webcache_to:
        kwargs["to"] = args.webcache_to
    if args.webcache_filter:
        kwargs["filter"] = list(args.webcache_filter)

    for obj in fetcher.iter(query, **kwargs):
        original = obj["url"]
        if source == "ia" and obj.get("timestamp"):
            link = web.wayback_snapshot_url(obj["timestamp"], original)
        else:
            link = original

        for k, v in args.url_renames.items():
            link = link.replace(k, v)

        mime = str(obj.get("mime") or "")
        link_text = strings.remove_consecutive_whitespace(mime)

        if is_desired_url(args, link, link_text, "", ""):
            yield {"link": link, "link_text": link_text, "before_text": "", "after_text": "", "mime": mime}


def iter_links(args, url):
    """Yield link dicts for a single URL, using the CDX extractor when --webcache is set."""
    if getattr(args, "webcache", False) and not web.is_wayback_url(url):
        yield from get_cdx_urls(args, url)
    else:
        yield from get_inner_urls(args, url)


def dedup_key(url: str) -> str:
    return web.wayback_normalize(urldefrag(url)[0])


def is_followable(args, link, d) -> bool:
    if args.local_html:
        return True

    mime = d.get("mime")
    if mime:
        return any(s in mime for s in web.HTML_MIME_TYPES + web.XML_MIME_TYPES)

    return web.is_html(args, link)


def url_parent_prefix(url: str) -> str:
    """Return scheme://netloc/parent/ for a seed URL (dropping the final file segment)."""
    parsed = urlparse(web.wayback_normalize(url))
    path = parsed.path
    if not path.endswith("/"):
        path = path.rsplit("/", 1)[0] + "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def is_within_parent(parent_prefix: str, link: str) -> bool:
    parent = urlparse(parent_prefix)
    child = urlparse(urldefrag(web.wayback_normalize(link))[0])
    # Ignore scheme so http->https redirects within the same host are still followed
    return child.netloc == parent.netloc and child.path.startswith(parent.path)


def crawl(args, seeds):
    """Yield filtered link dicts reachable from seeds, spidering only within each seed's parent directory.

    Links pointing outside the seed domain/parent are still yielded (so they can be
    downloaded) but are not followed. Wayback Machine URLs are collapsed to their
    original archived URL: sibling pages that only exist under a different timestamp
    are still followed, but multiple captures of the same page are collapsed so only
    one copy of each page is downloaded.
    """
    prefixes = [url_parent_prefix(seed) for seed in seeds]
    queue = deque(seeds)
    scheduled = set()
    spidered = set()
    yielded = set()

    while queue:
        url = queue.popleft()
        url_key = urldefrag(url)[0]
        if url_key in spidered:
            continue
        spidered.add(url_key)

        if not (getattr(args, "webcache", False) and not web.is_wayback_url(url)):
            # only mark the original as seen when its page content is actually processed
            original = dedup_key(url)
            scheduled.add(original)
            yielded.add(original)

        for d in iter_links(args, url):
            link = d["link"]
            link_key = urldefrag(link)[0]
            link_original = dedup_key(link)

            if link_original not in yielded:
                yielded.add(link_original)
                yield d

            if link_key in spidered or link_original in scheduled:
                continue
            if not any(is_within_parent(prefix, link) for prefix in prefixes):
                continue
            if not is_followable(args, link, d):
                continue

            scheduled.add(link_original)
            queue.append(link)


def _builtin_download(args, url) -> None:
    try:
        web.download_link(args, url)
    except (RuntimeError, requests.RequestException, ValueError, OSError) as excinfo:
        log.error("[%s]: %s", url, excinfo)
        raise


def _download_one(args, url, backend_args_cache) -> None:
    """Download a single URL with the downloader chosen by `args.profile` (auto by default).

    These commands are database-less, so yt-dlp/gallery-dl downloads are not recorded; only
    the database download command records results.
    """
    # local import: library.download imports this module at module level
    from library.download import download as download_mod

    if getattr(args, "safe", False) and not download_mod.safe_supported(args, url):
        log.info("Skipping unsupported URL (safe_mode) %s", url)
        return

    download_mod.route_links(
        args,
        {"path": url},
        url,
        [url],
        backend_args_cache,
        lambda _args, _m, _original_path, urls: [_builtin_download(_args, u) for u in urls],
    )


def print_or_download(args, d, backend_args_cache):
    url = d["link"]
    if args.download:
        _download_one(args, url, backend_args_cache)
    else:
        if not args.no_url_decode:
            url = path_utils.url_decode(url).strip()
        if args.verbose >= consts.LOG_DEBUG:
            printing.pipe_print(json.dumps(d, ensure_ascii=False))
        else:
            printing.pipe_print(url)


def download_paths(args, backend_args_cache) -> None:
    for url in shell_utils.gen_paths(args):
        if getattr(args, "url_encode", False):
            encoded_url = web.url_encode(url).strip()
        else:
            encoded_url = url
        if args.download:
            _download_one(args, encoded_url, backend_args_cache)
        else:
            printing.pipe_print(encoded_url)


def extract_links() -> None:
    run_extract(parse_args_extract())


def links_download() -> None:
    # local import: library.download imports this module at module level
    from library.download import download as download_mod

    download_mod.download_links()


def run_extract(args) -> None:
    backend_args_cache = {}

    if args.selenium:
        web.load_selenium(args)
    try:
        if args.recursive:
            for d in crawl(args, list(shell_utils.gen_paths(args))):
                print_or_download(args, d, backend_args_cache)
        else:
            for url in shell_utils.gen_paths(args):
                for d in iterables.return_unique(iter_links, lambda d: d["link"])(args, url):
                    print_or_download(args, d, backend_args_cache)

    finally:
        if args.selenium:
            web.quit_selenium(args)
