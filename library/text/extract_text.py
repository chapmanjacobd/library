from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import NavigableString

from library import usage
from library.createdb import fs_add_metadata
from library.utils import arggroups, argparse_utils, devices, file_utils, iterables, printing, strings, web
from library.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.extract_text)
    arggroups.requests(parser)
    arggroups.selenium(parser)

    parser.add_argument("--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument("--skip-links", action="store_true")
    parser.add_argument("--download", "--save", "--write", action="store_true")

    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)

    return args


def parse_text(args, html_content):
    soup = BeautifulSoup(html_content, "lxml")

    for item in soup.find_all():
        if item.name in ["meta"]:
            continue

        for descendant in item.descendants:
            if isinstance(descendant, NavigableString):
                parent = descendant.find_parent()
                parent_name = parent.name if parent else None

                if parent_name == "a":
                    if not args.skip_links:
                        yield strings.un_paragraph(descendant.get_text(strip=True))
                else:
                    yield strings.un_paragraph(descendant.get_text(strip=True))


def get_text(args, url):
    is_error = False
    if not args.local_html and not url.startswith("http") and Path(url).is_file():
        text = fs_add_metadata.munge_book_tags_fast(url)
        if text:
            tags = text.get("tags")
            if tags:
                yield tags.replace(";", "\n")
        return None

    if args.selenium:
        web.selenium_get_page(args, url)

        if args.manual:
            while devices.confirm("Extract HTML from browser?"):
                markup = web.selenium_extract_html(args.driver)
                yield from parse_text(args, markup)
        else:
            for markup in web.infinite_scroll(args.driver):
                yield from parse_text(args, markup)
    else:
        if args.local_html:
            with open(url) as f:
                markup = f.read()
            url = "file://" + url
        else:
            try:
                r = web.session.get(url, timeout=120)
            except Exception:
                log.exception("Could not get a valid response from the server")
                return None
            if r.status_code == 404:
                log.warning("404 Not Found Error: %s", url)
                is_error = True
            else:
                r.raise_for_status()
            markup = r.content

        yield from parse_text(args, markup)

    web.sleep(args)

    if is_error:
        return None


def extract_text() -> None:
    args = parse_args()

    if args.selenium:
        web.load_selenium(args)
    try:
        for url in file_utils.gen_paths(args):
            output_lines = []
            for s in iterables.return_unique(get_text)(args, url):
                if s is None:
                    break

                if args.download:
                    output_lines.append(s)
                else:
                    printing.pipe_print(s)

            if args.download:
                save_path = web.url_to_local_path(url)
                Path(save_path).parent.mkdir(exist_ok=True, parents=True)
                with open(save_path, "w") as f:
                    f.writelines(s + "\n" for s in output_lines)
    finally:
        if args.selenium:
            web.quit_selenium(args)
