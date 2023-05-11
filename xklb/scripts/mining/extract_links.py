import argparse

from xklb import consts
from xklb.utils import log, pipe_print


def get_page_links(url, include=None, exclude=None) -> None:
    from urllib.parse import urlparse

    import requests
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(requests.get(url, timeout=120).content, "html.parser")
    film_list = set()

    for a in soup.findAll("a", attrs={"href": True}):
        log.debug(a)

        href = a["href"].strip()
        if (len(href) > 1) and href[0] != "#":
            if any(s in href for s in (exclude or [])):
                log.debug("excluded: %s", href)
                continue

            up = urlparse(url)
            full_path = up.scheme + "://" + up.netloc + href
            if include is None or len(include) == 0:
                film_list.add(full_path)
            elif all(s in href for s in include):
                log.debug("included: %s", href)
                film_list.add(full_path)
            else:
                log.debug("else: %s", href)

        # breakpoint()

    pipe_print("\n".join(film_list))


def extract_links() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include", "-s", nargs="*", help="substrings for inclusion (all must match to include)")
    parser.add_argument(
        "--exclude",
        "-E",
        nargs="*",
        default=["javascript:", "mailto:", "tel:"],
        help="substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument("filename", help="File with one URL per line")
    args = parser.parse_args()

    with open(args.filename, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            if line in ["", '""', "\n"]:
                continue

            get_page_links(line, include=args.include, exclude=args.exclude)


if __name__ == "__main__":
    # echo $directors | python scripts/mining/nfb.ca.py | tee -a ~/.jobs/75
    extract_links()
