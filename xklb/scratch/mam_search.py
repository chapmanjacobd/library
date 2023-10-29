import argparse, json, time
from pathlib import Path

from pyparsing import nums

from xklb.utils import db_utils, iterables, nums, objects, web
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
        data = response.json()
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

    return df.to_dict(orient="records"), data["found"]


def search():
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
            "searchType": "active",  # fl-VIP, fl, VIP, all
            "searchIn": "torrents",
            "browseFlagsHideVsShow": 0,
            "cat": [
                39,
                49,
                97,
                40,
                41,
                42,
                52,
                98,
                54,
                55,
                99,
                45,
                87,
                119,
                59,
                46,
                47,
                89,
                100,
                108,
                48,
                111,
                71,
                61,
                101,
                107,
                79,
                118,
                127,
                130,
                128,
                132,
                0,
            ],
            # "main_cat": [13, 16],
            "sortType": "dateDesc",
            "startNumber": 0,
            "minSeeders": 1,
            "maxSeeders": 0,
            "minSnatched": 0,  # 80
            "maxSnatched": 0,
            "minSize": 0,
            "maxSize": 0,
        },
        "description": "true",
        "thumbnail": "false",
    }

    df, len_found = get_page(args, query_data)
    page_size = len(df)

    args.db["media"].upsert_all(iterables.list_dict_filter_bool(df), pk="id", alter=True)

    for page_number, current_start in enumerate(range(page_size, len_found, page_size), start=2):
        log.info("Getting page %s", page_number)

        query_data["tor"]["startNumber"] = current_start
        df, _ = get_page(args, query_data)

        args.db["media"].upsert_all(iterables.list_dict_filter_bool(df), pk="id", alter=True)

        time.sleep(1)


if __name__ == "__main__":
    search()
