import sqlite3

from library import usage
from library.utils import arggroups, argparse_utils, iterables, web
from library.utils.log_utils import log
from library.utils.objects import traverse_obj


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.getty_add)
    arggroups.requests(parser)

    arggroups.debug(parser)
    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser, create_db=True)

    web.requests_session(args)  # prepare requests session

    return args


def getty_fetch(url):
    log.debug("Fetching %s...", url)

    try:
        r = web.session.get(url, timeout=120)
    except Exception as e:
        if "too many 429 error" in str(e):
            raise
        log.exception("Could not get a valid response from the server")
        return None
    if r.status_code == 404:
        log.warning("404 Not Found Error: %s", url)
        return None
    else:
        r.raise_for_status()

    # time.sleep(random.uniform(0.05, 0.6))  # 300ms is politeness

    return r.json()


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


def update_activity_stream(args):
    current_page = int(args.db.pop("select max(page) from activity_stream") or 0) + 1

    next_page_url = f"https://data.getty.edu/museum/collection/activity-stream/page/{current_page}"
    while next_page_url:
        page_data = getty_fetch(next_page_url)
        if page_data:
            current_page = int(page_data["id"].split("/")[-1])

            activities = activity_stream_extract(args, page_data)
            args.db["activity_stream"].insert_all(
                [{"page": current_page, **activity} for activity in activities], alter=True, replace=True, pk="id"
            )

            next_page_url = page_data.get("next", {}).get("id")
        else:
            break


def objects_extract(args, j):
    assert j["type"] == "HumanMadeObject"

    known_keys = set(
        [
            "@context",
            "id",
            "type",
            "_label",
            "classified_as",
            "identified_by",
            "referred_to_by",
            "dimension",
            "shows",
            "produced_by",
            "current_keeper",
            "current_location",
            "current_owner",
            "subject_of",
            "representation",
            "subject_to",
            "member_of",
            "part_of",
            "carries",
            "changed_ownership_through",
            "attributed_by",
            "made_of",
            "part",
            "number_of_parts",
        ]
    )
    unhandled_keys = set(j.keys()) - known_keys
    if unhandled_keys:
        log.warning("Unhandled keys %s", {k: v for k, v in j.items() if k in unhandled_keys})

    ignore_types = set(["Object Record Structure: Whole"])

    description = None
    object_description = iterables.find_dict_value(
        j["referred_to_by"], _label="Object Description", format="text/markdown"
    )
    if object_description:
        description = object_description["content"]
        description += ";".join(d["content"] for d in object_description["subject_to"] for d in d["subject_of"])

    author = traverse_obj(j, ["produced_by", "referred_to_by"])
    if author:
        author = iterables.find_dict_value(author, _label="Artist/Maker (Producer) Description").get("content")

    # TODO: deprecated but I don't want to make another HTTP call... calling their bluff
    image_path = [
        d["id"]
        for d in (j.get("representation") or [])  # but some objects don't have images...
        if d["id"].startswith("https://media.getty.edu/iiif/image/")
    ]
    if j.get("representation"):
        assert len(image_path) == 1
        image_path = image_path[0]

    media_path = [d["id"] for d in (j.get("shows") or []) if d["id"].startswith("https://data.getty.edu/media/image/")]
    # assert len(media_path) == 1
    media_path = "|".join(media_path)

    timestamp_created = traverse_obj(j, ["produced_by", "timespan", "begin_of_the_begin"]) or traverse_obj(
        j, ["produced_by", "timespan", "end_of_the_end"]
    )

    d = {
        "path": image_path or None,
        "title": j["_label"],
        "types": "; ".join(set(d["_label"] for d in j["classified_as"]) - ignore_types),
        "description": description,
        "culture": iterables.find_dict_value(j["referred_to_by"], _label="Culture Statement").get("content"),
        "dimensions": iterables.find_dict_value(j["referred_to_by"], _label="Dimensions Statement").get("content"),
        "materials": iterables.find_dict_value(j["referred_to_by"], _label="Materials Description").get("content"),
        "author": author,
        "place_created": iterables.find_dict_value(j["referred_to_by"], _label="Place Created").get("content"),
        "object_path": j["id"],
        "media_path": media_path or None,
        "timestamp_created": timestamp_created,
        "license": j["referred_to_by"][-1]["id"],
    }

    return [d]


def update_objects(args):
    try:
        unknown_objects = [
            d["path"]
            for d in args.db.query(
                """
                SELECT DISTINCT path FROM activity_stream WHERE type = 'HumanMadeObject'
                EXCEPT
                SELECT object_path FROM media
                """
            )
        ]
    except sqlite3.OperationalError:
        unknown_objects = [
            d["path"] for d in args.db.query("SELECT DISTINCT path FROM activity_stream WHERE type = 'HumanMadeObject'")
        ]

    print("Fetching", len(unknown_objects), "unknown objects")

    for unknown_object in unknown_objects:
        log.debug("Fetching %s...", unknown_object)

        page_data = getty_fetch(unknown_object)
        if page_data:
            images = objects_extract(args, page_data)
            args.db["media"].insert_all(images, alter=True, pk="id")
        else:
            args.db["media"].insert({"title": "404 Not Found", "object_path": unknown_object}, alter=True, pk="id")


def getty_add():
    args = parse_args()

    update_activity_stream(args)

    """
    ┌─────────────────────┬──────────┐
    │        type         │ count(*) │ collection_type
    ├─────────────────────┼──────────┤
    │ PropositionalObject │ 10480    │ exhibition
    │ Activity            │ 11376    │ activity
    │ Group               │ 13383    │ group
    │ Place               │ 24977    │ place
    │ Person              │ 41438    │ person
    │ LinguisticObject    │ 73273    │ document
    │ HumanMadeObject     │ 319018   │ object  # the one that is most interesting...
    └─────────────────────┴──────────┘
    """

    update_objects(args)
