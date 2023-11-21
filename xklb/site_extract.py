import argparse, itertools, json
from collections import defaultdict
from pathlib import Path

from xklb import usage
from xklb.utils import db_utils, iterables, objects, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library site-add", usage=usage.site_add)
    parser.add_argument("--auto-pager", "--autopager", action="store_true")
    parser.add_argument("--poke", action="store_true")
    parser.add_argument("--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument("--file", "-f", help="File with one URL per line")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def extract_tables(dict_, table_name):
    dict_ = objects.flatten_dict_single_parents(dict_)
    dict_ = objects.flatten_grandparents(dict_)

    tables = []
    simple_dict = {}
    child_table_name = None
    for key, value in dict_.items():
        if isinstance(value, list):
            arr_ = value
            if all(isinstance(s, str) for s in arr_):
                simple_dict[key] = ", ".join(arr_)
            else:
                child_table_name = key if table_name is None else f"{table_name}_{key}"
                # TODO: add foreign keys: itertools.count(start=1) for each parent table
                tables.extend(nosql_to_sql(arr_, table_name=child_table_name))
        else:
            simple_dict[key] = value

    if simple_dict:
        if table_name is None and child_table_name is not None:
            table_name = child_table_name + "_root"
        log.debug("simple_dict: %s", simple_dict)
        tables.append({"table_name": table_name, "data": [simple_dict]})

    return tables


def nosql_to_sql(dict_or_arr, table_name=None):
    tables = []

    if isinstance(dict_or_arr, list):
        arr_ = dict_or_arr
        new_records = defaultdict(list)
        scalar_values = []
        for value in arr_:
            if isinstance(value, dict):
                dict_ = value
                sub_tables = extract_tables(dict_, table_name)
                for t in sub_tables:
                    new_records[t["table_name"]].extend(t["data"])
            else:
                scalar_values.append(value)

        if scalar_values:
            log.debug("array of scalar: %s", arr_)
            arr_ = [{"v": v} for v in scalar_values]
            tables.append({"table_name": table_name, "data": arr_})

        for table_name, data in new_records.items():
            log.debug("array of dicts: %s", arr_)
            tables.append({"table_name": table_name, "data": data})

    elif isinstance(dict_or_arr, dict):
        dict_ = dict_or_arr
        tables.extend(extract_tables(dict_, table_name))

    else:
        raise ValueError("Expected dict, list of dicts, or list of scalar values")

    return tables


def add_missing_table_names(args, tables):
    if all(d["table_name"] for d in tables):
        return tables

    existing_tables = list(args.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 't%'"))
    table_id_gen = itertools.count(start=1)

    tables = sorted(tables, key=lambda d: len(d["data"]), reverse=True)
    for d in tables:
        if d["table_name"] is None:
            table_name = f"t{next(table_id_gen)}"
            while table_name in existing_tables:
                table_name = f"t{next(table_id_gen)}"
            d["table_name"] = table_name

    return tables


def save_path_data(args, path):
    from seleniumwire.utils import decode

    web.selenium_get_page(args, path)

    for page_html_text in web.infinite_scroll(args.driver):
        # TODO: extract HTML tables (via pandas?)
        # TODO: websockets, protobufs...

        for request in args.driver.requests:
            host = request.host.lower()
            request_path = request.path.lower()
            if (
                host.endswith((".mozilla.com", ".mozilla.net", ".firefox.com"))
                or any(s in host for s in ("ublockorigin",))
                or any(s in request_path for s in ("ublock",))
            ):
                continue

            r = request.response
            if (
                r
                and r.status_code // 100 == 2  # HTTP 2xx
                and "Content-Type" in r.headers
                and r.headers["Content-Type"].startswith(("application/json",))
            ):
                body = decode(r.body, r.headers.get("Content-Encoding", "identity"))
                body = body.decode()
                if any(s in body for s in ["searchKeywords"]):
                    continue

                body = json.loads(body)
                tables = nosql_to_sql(body)
                if args.verbose > 2:
                    breakpoint()

                tables = add_missing_table_names(args, tables)
                for d in tables:
                    args.db[d["table_name"]].insert_all(iterables.list_dict_filter_bool(d["data"]), alter=True)

            elif (
                r
                and "Content-Type" in r.headers
                and r.headers["Content-Type"].startswith(
                    (
                        "application/javascript",
                        "image/jpeg",
                        "image/vnd.microsoft.icon",
                        "text/css",
                        "text/html",
                    )
                )
            ):
                pass
            elif r:
                log.info("%s\t%s\t%s", request.url, r.headers["Content-Type"], r.status_code)

        # del args.driver.requests  # idk if this is needed or not


def site_add(args=None) -> None:
    args = parse_args()

    web.load_selenium(args, wire=True)
    try:
        if args.file:
            with open(args.file) as f:
                for line in f:
                    url = line.rstrip("\n")
                    if url in ["", '""', "\n"]:
                        continue
                    save_path_data(args, url)
        else:
            for url in args.paths:
                if url in ["", '""', "\n"]:
                    continue
                save_path_data(args, url)
    finally:
        web.quit_selenium(args)
