from library.utils import arggroups, argparse_utils, web
from library.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser()
    arggroups.requests(parser)

    arggroups.debug(parser)
    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser, create_db=True)

    web.requests_session(args)  # prepare requests session

    return args


def activity_stream_extract(args, json_data):
    assert json_data["type"] == "OrderedCollectionPage"

    data = []
    if "orderedItems" in json_data:
        for item in json_data["orderedItems"]:
            for k in ["id", "created", "endTime"]:
                item.pop(k)
            obj = item.pop("object")

            type_ = item.pop("type")
            if type_ == "Delete":
                with args.db.conn:
                    args.db["activity_stream"].delete_where("path = ?", [obj.get("id")])
            elif type_ == "Update":
                continue  # TODO: implement in-band Update mechanism
            elif type_ not in ["Create"]:
                raise

            obj_info = {
                "path": obj.get("id"),
                "type": obj.get("type"),
                **{k: v for k, v in obj.items() if k not in ["id", "type"]},
            }
            data.append(obj_info)
            if item:
                print("item", item)

    else:
        raise

    return data


def activity_stream_fetch(url):
    try:
        r = web.session.get(url, timeout=120)
    except Exception as e:
        if "too many 429 error" in str(e):
            raise
        log.exception("Could not get a valid response from the server")
        return None
    if r.status_code == 404:
        log.warning("404 Not Found Error: %s", url)
        return
    else:
        r.raise_for_status()

    # time.sleep(random.uniform(0.05, 0.6))  # 300ms is politeness

    return r.json()


def update_activity_stream(args):
    current_page = int(args.db.pop("select max(page) from activity_stream") or 0) + 1

    next_page_url = f"https://data.getty.edu/museum/collection/activity-stream/page/{current_page}"
    while next_page_url:
        log.debug("Fetching %s...", next_page_url)

        page_data = activity_stream_fetch(next_page_url)
        if page_data:
            current_page = int(page_data["id"].split("/")[-1])

            activities = activity_stream_extract(args, page_data)
            args.db["activity_stream"].insert_all(
                [{"page": current_page, **activity} for activity in activities], alter=True, replace=True  # pk="id",
            )

            next_page_url = page_data.get("next", {}).get("id")
        else:
            break


def getty_add():
    args = parse_args()

    update_activity_stream(args)


# https://data.getty.edu/museum/collection/group/ee294bfc-bbe5-42b4-95b2-04872b802bfe
# https://data.getty.edu/museum/collection/object/08eaed9f-1354-4817-8aed-1db49e893a03
# https://data.getty.edu/museum/collection/document/37194afd-905c-43df-9f28-baacdd91062a
# https://data.getty.edu/museum/collection/person/f4806477-b058-4852-88ae-852a99465249
# https://data.getty.edu/museum/collection/place/ed18d1db-1ed7-4d04-a46a-909c054dc762
# https://data.getty.edu/museum/collection/exhibition/6bd62de5-391f-45a9-95f0-bc88d4bcc2a8
