import argparse, re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString

from xklb import usage
from xklb.utils import arg_utils, devices, iterables, printing, strings, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(prog="library extract-text", usage=usage.extract_text)
    parser.add_argument("--skip-links", action="store_true")
    parser.add_argument("--save", action="store_true")

    parser.add_argument("--cookies", help="path to a Netscape formatted cookies file")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]")
    parser.add_argument("--selenium", action="store_true")
    parser.add_argument("--manual", action="store_true", help="Confirm manually in shell before exiting the browser")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--auto-pager", "--autopager", action="store_true")
    parser.add_argument("--poke", action="store_true")
    parser.add_argument("--chrome", action="store_true")

    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("--local-file", "--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument("--file", "-f", help="File with one URL per line")

    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    if args.scroll:
        args.selenium = True

    return args


def un_paragraph(item):
    s = strings.remove_consecutive_whitespace(item.get_text(strip=True))
    s = re.sub(r"[“”‘’]", "'", s)
    s = re.sub(r"[‛‟„]", '"', s)
    s = re.sub(r"[…]", "...", s)
    return s


def parse_text(args, html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for item in soup.find_all():
        if item.name in ["meta"]:
            continue

        for descendant in item.descendants:
            if isinstance(descendant, NavigableString):
                parent = descendant.find_parent()
                parent_name = parent.name if parent else None

                if parent_name == "a":
                    if not args.skip_links:
                        yield un_paragraph(descendant)
                else:
                    yield un_paragraph(descendant)


def get_text(args, url):
    is_error = False
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

        yield from parse_text(args, markup)

    if is_error:
        yield None


def extract_text() -> None:
    args = parse_args()

    if args.selenium:
        web.load_selenium(args)
    try:
        for url in arg_utils.gen_paths(args):
            output_lines = []
            for s in iterables.return_unique(get_text)(args, url):
                if s is None:
                    break

                if args.save:
                    output_lines.append(s)
                else:
                    printing.pipe_print(s)

            if args.save:
                save_path = web.url_to_local_path(url)
                Path(save_path).parent.mkdir(exist_ok=True, parents=True)
                with open(save_path, "w") as f:
                    f.writelines(s + "\n" for s in output_lines)
    finally:
        if args.selenium:
            web.quit_selenium(args)


if __name__ == "__main__":
    extract_text()
