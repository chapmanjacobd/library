import urllib.parse

from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils, web

COMMON_SITE_TITLE_SUFFIXES = [
    " | Listen online for free on SoundCloud",
    " - YouTube",
]


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.markdown_links)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.selenium_post(args)

    return args


def fake_title(url):
    p = urllib.parse.urlparse(url)
    title = f"{p.netloc} {p.path} {p.params} {p.query}: {p.fragment}"

    if title.startswith("www."):
        title = title[4:]

    title = title.replace("/", " ")
    title = title.replace("?", " ")
    title = title.replace("#", ": ")

    return title.strip()


def markdown_links():
    args = parse_args()

    import requests
    from bs4 import BeautifulSoup

    if args.selenium:
        web.load_selenium(args)
    try:
        for url in arg_utils.gen_paths(args):
            try:
                if args.selenium:
                    web.selenium_get_page(args, url)
                    html_text = args.driver.page_source
                else:
                    html_text = web.requests_session(args).get(url).text

                soup = BeautifulSoup(html_text, "lxml")
                title = soup.title.text.strip() if soup.title else url
            except requests.exceptions.RequestException as e:
                title = fake_title(url)

            if title.startswith("Stream ") and "SoundCloud" in title:
                title = title.replace("Stream ", "", 1)

            for x in COMMON_SITE_TITLE_SUFFIXES:
                title = title.replace(x, "")

            text = f"[{title}]({url})"
            if len(args.paths) > 1:
                print(f"- {text}")
            else:
                print(text)
    finally:
        if args.selenium:
            web.quit_selenium(args)


if __name__ == "__main__":
    markdown_links()
