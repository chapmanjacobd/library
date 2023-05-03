from xklb.utils import log, pipe_print


def get_page_links(url) -> None:
    from urllib.parse import urlparse

    import requests
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(requests.get(url, timeout=120).content, "html.parser")
    film_list = set()

    for a in soup.findAll("a", attrs={"href": True}):
        href = a["href"].strip()
        if all([len(href) > 1, href[0] != "#", "javascript:" not in href, "mailto:" not in href, "tel:" not in href]):
            if "/film/" in href:
                up = urlparse(url)
                film_list.add(up.scheme + "://" + up.netloc + href)
            else:
                log.debug(href)

    for el in film_list:
        pipe_print(el)


def nfb_films() -> None:
    import sys

    for line in sys.stdin:
        line = line.rstrip("\n")
        if line in ["", '""', "\n"]:
            continue

        get_page_links(line)


if __name__ == "__main__":
    # echo $directors | python scripts/mining/nfb.ca.py | tee -a ~/.jobs/todo/71_Mealtime_Videos
    nfb_films()
