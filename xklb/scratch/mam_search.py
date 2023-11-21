import argparse, json, time
from pathlib import Path
from sqlite3 import IntegrityError

from xklb.utils import db_utils, nums, objects, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--base-url", default="https://www.myanonamouse.net")
    parser.add_argument("--no-title", action="store_false")
    parser.add_argument("--no-author", action="store_false")
    parser.add_argument("--narrator", action="store_true")
    parser.add_argument("--series", action="store_true")
    parser.add_argument("--description", action="store_true")

    parser.add_argument("--books", action="store_true")
    parser.add_argument("--audiobooks", action="store_true")
    parser.add_argument("--comics", action="store_true")
    parser.add_argument("--cookbooks", action="store_true")
    parser.add_argument("--musicology", action="store_true")
    parser.add_argument("--radio", action="store_true")

    parser.add_argument("--cookie", required=True)

    parser.add_argument("database")
    parser.add_argument("search_text", nargs="+")
    args = parser.parse_args()

    Path(args.database).touch()
    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def get_page(args, query_data):
    import pandas as pd

    response = web.requests_session().post(
        f"{args.base_url}/tor/js/loadSearchJSONbasic.php",
        headers={"Content-Type": "application/json"},
        cookies={"mam_id": args.cookie},
        json=query_data,
    )
    response.raise_for_status()
    data = response.json()

    try:
        data_found = data["found"]
        data = data["data"]
    except KeyError:
        if "Nothing returned" in data["error"]:
            log.warning("No results found")
            raise SystemExit(4)
        else:
            raise RuntimeError(data["error"])

    df = pd.DataFrame(data)
    df = df.drop(columns=["cat", "language", "category", "main_cat", "browseflags", "comments", "owner", "leechers"])

    safe_json = objects.fallback(json.loads, {})
    dict_values_str = lambda d: ", ".join(d.values())
    dict_values_str = lambda d: ", ".join(d.values())
    dict_values_list = lambda d: list(d.values())
    df["author_info"] = df["author_info"].apply(safe_json).apply(dict_values_str)
    df["narrator_info"] = df["narrator_info"].apply(safe_json).apply(dict_values_str)
    df["series_info"] = df["series_info"].apply(safe_json).apply(dict_values_list)
    df["size_bytes"] = df["size"].apply(nums.human_to_bytes)

    log.debug(df)

    return df.to_dict(orient="records"), data_found


def save_to_db(args, data):
    for d in data:
        try:
            args.db["media"].insert(objects.dict_filter_bool(d), pk="id", alter=True)
        except IntegrityError:
            log.error("Reached existing id")
            raise SystemExit(0)


def mam_search():
    args = parse_args()

    query_data = {
        "tor": {
            "text": " ".join(args.search_text),
            "browse_lang": [1, 44],
            "srchIn": {
                "title": args.no_title,
                "author": args.no_author,
                "narrator": args.narrator,
                "series": args.series,
                "description": args.description,
            },
            "searchType": "all",  # fl-VIP, fl, VIP, all
            "searchIn": "torrents",
            "browseFlagsHideVsShow": 0,
            "cat": [],
            "sortType": "dateDesc",
            "startNumber": 0,
            "minSeeders": 0,
            "maxSeeders": 0,
            "minSnatched": 20,
            "maxSnatched": 0,
            "minSize": 0,
            "maxSize": 0,
        },
        "description": "true",
        "thumbnail": "false",
    }

    if args.cookbooks:
        query_data["tor"]["cat"].extend([107])
    if args.comics:
        query_data["tor"]["cat"].extend([61])
    if args.audiobooks:
        query_data["tor"]["cat"].extend(
            [
                39,  # Action/Adventure
                40,  # Crime/Thriller
                41,  # Fantasy
                42,  # General Fiction
                45,  # Literary Classics
                46,  # Romance
                47,  # Science Fiction
                48,  # Western
                49,  # Art
                52,  # General Non-Fic
                54,  # History
                55,  # Home/Garden
                59,  # Recreation
                87,  # Mystery
                89,  # Travel/Adventure
                97,  # Crafts
                98,  # Historical Fiction
                99,  # Humor
                100,  # True Crime
                108,  # Urban Fantasy
                111,  # Young Adult
                119,  # Nature
                # 43,  # Horror
                # 44,  # Juvenile
                # 50,  # Biographical
                # 51,  # Computer/Internet
                # 53,  # Self-Help
                # 56,  # Language
                # 57,  # Math/Science/Tech
                # 58,  # Pol/Soc/Relig
                # 83,  # Business
                # 84,  # Instructional
                # 85,  # Medical
                # 88,  # Philosophy
                # 106,  # Food
            ]
        )
    if args.books:
        query_data["tor"]["cat"].extend(
            [
                71,  # Art
                79,  # Magazines/Newspapers
                101,  # Crafts
                118,  # Mixed Collections
                # 60,  # Action/Adventure
                # 62,  # Crime/Thriller
                # 63,  # Fantasy
                # 64,  # General Fiction
                # 65,  # Horror
                # 66,  # Juvenile
                # 67,  # Literary Classics
                # 68,  # Romance
                # 69,  # Science Fiction
                # 70,  # Western
                # 72,  # Biographical
                # 73,  # Computer/Internet
                # 74,  # General Non-Fiction
                # 75,  # Self-Help
                # 76,  # History
                # 77,  # Home/Garden
                # 78,  # Language
                # 80,  # Math/Science/Tech
                # 81,  # Pol/Soc/Relig
                # 82,  # Recreation
                # 90,  # Business
                # 91,  # Instructional
                # 92,  # Medical
                # 94,  # Mystery
                # 95,  # Philosophy
                # 96,  # Travel/Adventure
                # 102,  # Historical Fiction
                # 103,  # Humor
                # 104,  # True Crime
                # 109,  # Urban Fantasy
                # 112,  # Young Adult
                # 115,  # Illusion/Magic
                # 120,  # Nature
            ]
        )
    if args.musicology:
        query_data["tor"]["cat"].extend(
            [
                17,  # Music - Complete Editions
                19,  # Guitar/Bass Tabs
                20,  # Individual Sheet
                22,  # Instructional Media - Music
                24,  # Individual Sheet MP3
                26,  # Music Book
                27,  # Music Book MP3
                30,  # Sheet Collection
                31,  # Sheet Collection MP3
                113,  # Lick Library - LTP/Jam With
                114,  # Lick Library - Techniques/QL
                126,  # Instructional Book with Video
            ]
        )
    if args.radio:
        query_data["tor"]["cat"].extend(
            [
                127,  # Comedy
                128,  # Factual/Documentary
                130,  # Drama
                132,  # Reading
            ]
        )
    if len(query_data["tor"]["cat"]) == 0:
        query_data["tor"]["cat"] = [0]

    data, len_found = get_page(args, query_data)
    page_size = len(data)

    save_to_db(args, data)

    for page_number, current_start in enumerate(range(page_size, len_found, page_size), start=2):
        log.info("Getting page %s", page_number)

        query_data["tor"]["startNumber"] = current_start
        data, _ = get_page(args, query_data)

        save_to_db(args, data)

        time.sleep(1)


if __name__ == "__main__":
    mam_search()
