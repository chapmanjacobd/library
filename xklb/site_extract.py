import argparse, json
from collections import defaultdict
from io import StringIO
from pathlib import Path

from xklb import usage
from xklb.utils import consts, db_utils, iterables, objects, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library site-add", usage=usage.siteadd)
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


def attach_interceptors(args):
    from seleniumwire.utils import decode

    def request_interceptor(request):
        if request.path.endswith((".png", ".jpg", ".gif")):
            request.abort()

    args.driver.request_interceptor = request_interceptor  # type: ignore

    def response_interceptor(request, response):
        # TODO: websockets, protobufs...

        host = request.host.lower()
        request_path = request.path.lower()
        if (
            host.endswith((".mozilla.com", ".mozilla.net", ".firefox.com"))
            or any(s in host for s in ("ublockorigin",))
            or any(s in request_path for s in ("ublock",))
        ):
            return

        if (
            response
            and response.status_code // 100 == 2  # HTTP 2xx
            and "Content-Type" in response.headers
            and response.headers["Content-Type"].startswith(("application/json",))
        ):
            body = decode(response.body, response.headers.get("Content-Encoding", "identity"))
            body = body.decode()
            if any(s in body for s in ["searchKeywords"]):
                return

            body = json.loads(body)
            tables = nosql_to_sql(body)
            if args.verbose > 2:
                breakpoint()

            tables = db_utils.add_missing_table_names(args, tables)
            db_thread = db_utils.connect(argparse.Namespace(database=args.database, verbose=args.verbose))
            for d in tables:
                db_thread[d["table_name"]].insert_all(iterables.list_dict_filter_bool(d["data"]), alter=True)  # type: ignore

        elif (
            response
            and "Content-Type" in response.headers
            and response.headers["Content-Type"].startswith(
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
        elif response:
            log.info("%s\t%s\t%s", request.url, response.headers["Content-Type"], response.status_code)

        request = None
        response = None  # tell selenium-wire to not keep the response... idk if this works

    args.driver.response_interceptor = response_interceptor  # type: ignore


def load_page(args, path):
    if args.local_html:
        web.save_html_table(args, path)
        return

    from selenium.common.exceptions import WebDriverException

    attach_interceptors(args)
    web.selenium_get_page(args, path)

    while True:  # repeat until browser closed
        try:
            if args.auto_pager:
                for _page_html_text in web.infinite_scroll(args.driver):
                    args.driver.implicitly_wait(1)
            else:
                args.driver.implicitly_wait(5)  # give the interceptors some time to work
        except WebDriverException:
            break
        else:
            del args.driver.requests  # clear processed responses

            web.save_html_table(args, StringIO(web.extract_html_text(args.driver)))

            if args.verbose < consts.LOG_DEBUG:
                break  # if browser hidden, exit


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
                    load_page(args, url)
        else:
            for url in args.paths:
                if url in ["", '""', "\n"]:
                    continue
                load_page(args, url)
    finally:
        web.quit_selenium(args)
