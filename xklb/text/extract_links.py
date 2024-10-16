import json

from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils, consts, devices, iterables, printing, strings, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.extract_links)
    arggroups.extractor(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)

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
    include_cond = all if args.strict_include else any
    exclude_cond = all if args.strict_exclude else any

    link_lower = link if args.case_sensitive else link.lower()
    link_text_lower = link_text if args.case_sensitive else link_text.lower()

    if args.path_include and not include_cond(inc in link_lower for inc in args.path_include):
        log.debug("no match path-include: %s", link_lower)
        return False
    if args.path_exclude and exclude_cond(ex in link_lower for ex in args.path_exclude):
        log.debug("matched path-exclude: %s", link_lower)
        return False

    if args.text_exclude and exclude_cond(ex in link_text_lower for ex in args.text_exclude):
        log.debug("matched text-exclude: %s", link_text_lower)
        return False
    if args.text_include and not include_cond(inc in link_text_lower for inc in args.text_include):
        log.debug("no match text-include: %s", link_text_lower)
        return False

    if args.before_exclude or args.before_include:
        if args.before_include and not before:
            return False

        before_text = before if args.case_sensitive else before.lower()

        if args.before_exclude and exclude_cond(ex in before_text for ex in args.before_exclude):
            log.debug("matched before-exclude: %s", before_text)
            return False
        if args.before_include and not include_cond(inc in before_text for inc in args.before_include):
            log.debug("no match before-include: %s", before_text)
            return False

        if args.before_exclude or args.before_include:  # just logging
            log.info("  before: %s", before_text)

    if args.after_exclude or args.after_include:
        if args.after_include and not after:
            return False

        after_text = after if args.case_sensitive else after.lower()

        if args.after_exclude and exclude_cond(ex in after_text for ex in args.after_exclude):
            log.debug("matched after-exclude: %s", after_text)
            return False
        if args.after_include and not include_cond(inc in after_text for inc in args.after_include):
            log.debug("no match after-include: %s", after_text)
            return False

        if args.after_exclude or args.after_include:  # just logging
            log.info("  after: %s", after_text)

    if args.text_exclude or args.text_include:  # just logging
        log.info("  text: `%s`", link_text_lower.strip())

    return True


def parse_inner_urls(args, url, markup):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(markup, "lxml")

    link_attrs = set()
    if args.href:
        link_attrs.add("href")
    if args.src:
        link_attrs.add("src")
    if args.url:
        link_attrs.add("url")
    if args.data_src:
        link_attrs.update({"data-src", "data-url", "data-original"})

    url_renames = args.url_renames.items()

    def delimit_fn(el):
        return any(el.has_attr(s) for s in link_attrs)

    tags = web.tags_with_text(soup, delimit_fn)
    for tag in tags:
        for attr_name, attr_value in tag.attrs.items():
            if attr_name not in link_attrs:
                continue

            attr_value = str(attr_value).strip()
            if attr_value and attr_value[0] != "#":
                link = web.construct_absolute_url(url, attr_value)
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
            with open(url) as f:
                markup = f.read()
            url = "file://" + url
        else:
            try:
                r = web.session.get(url, timeout=120)
            except Exception as e:
                if "too many 429 error" in str(e):
                    raise
                log.exception("Could not get a valid response from the server")
                return None
            if r.status_code == 404:
                log.warning("404 Not Found Error: %s", url)
                is_error = True
            else:
                r.raise_for_status()
            markup = r.content

        yield from parse_inner_urls(args, url, markup)

    web.sleep(args)

    if is_error:
        return None


def print_or_download(args, d):
    url = d["link"]
    if args.download:
        try:
            web.download_url(args, url)
        except RuntimeError as e:
            log.error("[%s]: %s", url, e)
    else:
        if not args.no_url_decode:
            url = web.url_decode(url).strip()
        if args.verbose >= consts.LOG_DEBUG:
            printing.pipe_print(json.dumps(d, ensure_ascii=False))
        else:
            printing.pipe_print(url)


def extract_links() -> None:
    args = parse_args()

    if args.insert_only:
        for url in arg_utils.gen_paths(args):
            if args.url_encode:
                url = web.url_encode(url).strip()
            if args.download:
                try:
                    web.download_url(args, url)
                except RuntimeError as e:
                    log.error("[%s]: %s", url, e)
            else:
                printing.pipe_print(url)
        return

    if args.selenium:
        web.load_selenium(args)
    try:
        for url in arg_utils.gen_paths(args):
            for d in iterables.return_unique(get_inner_urls, lambda d: d["link"])(args, url):
                print_or_download(args, d)

    finally:
        if args.selenium:
            web.quit_selenium(args)


if __name__ == "__main__":
    extract_links()
