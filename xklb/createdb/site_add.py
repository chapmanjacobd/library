import argparse, json
from collections import defaultdict
from io import StringIO

from bs4 import BeautifulSoup, element

from xklb import usage
from xklb.text import extract_text
from xklb.utils import arg_utils, arggroups, argparse_utils, consts, db_utils, iterables, objects, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library site-add", usage=usage.site_add)
    arggroups.selenium(parser)
    parser.set_defaults(selenium=True)

    parser.add_argument("--local-file", "--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument(
        "--extract-html-table", action="store_true", help="Extract data from HTML tables within the page"
    )
    parser.add_argument("--extract-html", action="store_true", help="Extract data from HTML")
    parser.add_argument("--extract-xml", action="store_true", help="Extract data from XML")

    arggroups.debug(parser)
    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()

    arggroups.selenium_post(args)

    arggroups.args_post(args, parser, create_db=True)
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


def soup_tree(o) -> dict | str | None:
    if isinstance(o, BeautifulSoup):
        return soup_tree(o.contents)
    elif isinstance(o, element.Tag):
        tag_result = {}

        for attr in ("title", "href", "src", "alt"):
            if attr in o.attrs:
                tag_result[attr] = o.attrs[attr]

        val = soup_tree(o.contents)
        if isinstance(val, dict):
            tag_result.update(val)
        else:
            raise
        return tag_result

    elif isinstance(o, (element.ResultSet, list)):
        transformed = {}

        for el in o:
            val = soup_tree(el)
            if not val:
                continue

            el_type = type(el)
            key_name = str(el_type.__name__)
            if el_type == element.Tag:
                key_name = el.name
            elif isinstance(val, str):
                key_name = "text"

            if key_name in transformed:
                if isinstance(transformed[key_name], list):
                    if isinstance(val, list):
                        transformed[key_name].expand(val)
                    elif isinstance(val, (dict, str)):
                        transformed[key_name].append(val)

                elif isinstance(transformed[key_name], (dict, str)):
                    existing_value = transformed[key_name]
                    transformed[key_name] = [existing_value]
                    transformed[key_name].append(val)

                else:
                    raise NotImplementedError

            else:
                if isinstance(val, (dict, str)):
                    transformed[key_name] = val
                elif isinstance(val, list):
                    transformed[key_name] = []
                else:
                    raise NotImplementedError

        return transformed

    elif isinstance(
        o,
        (
            element.NavigableString,
            element.Comment,
            element.CData,
            element.ProcessingInstruction,
            element.XMLProcessingInstruction,
            element.Declaration,
            element.Doctype,
            element.TemplateString,
        ),
    ):
        text = extract_text.un_paragraph(o)
        if text:
            return text
        return None

    elif isinstance(
        o,
        (
            element.Stylesheet,
            element.Script,
        ),
    ):
        pass

    raise NotImplementedError


def html_to_dict(s):
    soup = BeautifulSoup(s, features="lxml")
    tree = soup_tree(soup)
    return tree


def attach_interceptors(args):
    from seleniumwire.utils import decode

    def request_interceptor(request):
        if request.path.endswith((".png", ".jpg", ".gif")):
            request.abort()

    args.driver.request_interceptor = request_interceptor  # type: ignore

    def response_interceptor(request, response):
        # TODO: websockets, protobufs...
        tables = []

        host = request.host.lower()
        request_path = request.path.lower()
        if (
            host.endswith((".mozilla.com", ".mozilla.net", ".firefox.com"))
            or any(s in host for s in ("ublockorigin",))
            or any(s in request_path for s in ("ublock",))
        ):
            return

        log.debug("%s\t%s\t%s", request.url, response.headers["Content-Type"], response.status_code)

        if not (response and response.status_code // 100 == 2 and "Content-Type" in response.headers):  # HTTP 2xx
            return

        if response.headers["Content-Type"].startswith(("application/json",)):
            body = decode(response.body, response.headers.get("Content-Encoding", "identity"))
            body = body.decode()
            if any(s in body for s in ["searchKeywords"]):
                return

            body = json.loads(body)
            tables = nosql_to_sql(body)

        elif args.extract_html and response.headers["Content-Type"].startswith(("text/html",)):
            body = decode(response.body, response.headers.get("Content-Encoding", "identity"))
            body = body.decode()

            o = html_to_dict(body)
            tables = nosql_to_sql(o)

        elif args.extract_xml and response.headers["Content-Type"].startswith(("text/xml", "application/xml")):
            body = decode(response.body, response.headers.get("Content-Encoding", "identity"))
            body = body.decode()

            import xmltodict

            o = xmltodict.parse(body)
            tables = nosql_to_sql(o)

        elif response.headers["Content-Type"].startswith(
            (
                "application/javascript",
                "image/jpeg",
                "image/vnd.microsoft.icon",
                "text/css",
                "text/html",
            )
        ):
            pass
        elif args.verbose == 1:
            log.info("%s\t%s\t%s", request.url, response.headers["Content-Type"], response.status_code)

        if len(tables) > 0:
            if args.verbose > 2:
                breakpoint()

            tables = db_utils.add_missing_table_names(args, tables)
            db_thread = db_utils.connect(argparse.Namespace(database=args.database, verbose=args.verbose))
            for d in tables:
                db_thread[d["table_name"]].insert_all(iterables.list_dict_filter_bool(d["data"]), alter=True)  # type: ignore

        request = None
        response = None  # tell selenium-wire to not keep the response... idk if this works

    args.driver.response_interceptor = response_interceptor  # type: ignore


def load_page(args, path):
    if args.local_html:
        path = "file://" + path

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

            if args.extract_html_table:
                web.save_html_table(args, StringIO(web.selenium_extract_html(args.driver)))

            if args.verbose < consts.LOG_DEBUG:
                break  # if browser hidden, exit


def site_add(args=None) -> None:
    args = parse_args()

    web.load_selenium(args, wire=True)
    try:
        for url in arg_utils.gen_paths(args):
            load_page(args, url)
    finally:
        web.quit_selenium(args)
