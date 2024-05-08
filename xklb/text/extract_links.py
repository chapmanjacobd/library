from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils, consts, devices, iterables, printing, strings, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(
        prog="library extract-links",
        usage=usage.extract_links,
    )
    arggroups.extractor(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)

    parser.add_argument("--print-link-text", "--print-title", action="store_true")
    parser.add_argument("--download", action="store_true", help="Download filtered links")
    parser.add_argument("--local-file", "--local-html", action="store_true", help="Treat paths as Local HTML files")

    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.extractor_post(args)
    arggroups.filter_links_post(args)
    arggroups.selenium_post(args)

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

    soup = BeautifulSoup(markup, "lxml")

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
        if args.local_html:
            with open(url) as f:
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

    if args.insert_only:
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
