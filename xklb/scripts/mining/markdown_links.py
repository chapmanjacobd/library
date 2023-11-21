import argparse, urllib.parse

from xklb.utils import arg_utils, web

COMMON_SITE_TITLE_SUFFIXES = [
    " | Listen online for free on SoundCloud",
    " - YouTube",
]


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--selenium", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    parser.add_argument("paths", nargs="*", action=arg_utils.ArgparseArgsOrStdin)
    args = parser.parse_args()

    import requests
    from bs4 import BeautifulSoup

    if args.selenium:
        web.load_selenium(args)
    try:
        for url in args.paths:
            url = url.strip()

            try:
                if args.selenium:
                    web.selenium_get_page(args, url)
                    html_text = args.driver.page_source
                else:
                    html_text = web.requests_session().get(url).text

                soup = BeautifulSoup(html_text, "html.parser")
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
