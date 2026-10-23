import argparse
from collections import defaultdict
from io import StringIO

from bs4 import BeautifulSoup, element

from library import usage
from library.utils import arggroups, argparse_utils, consts, db_utils, iterables, objects, shell_utils, strings, web
from library.utils.log_utils import log

HTTP_SUCCESS_CLASS = 2


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.site_add)
    arggroups.selenium(parser)
    parser.set_defaults(selenium=True)

    parser.add_argument("--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument(
        "--extract-html-table", action="store_true", help="Extract data from HTML tables within the page"
    )
    parser.add_argument("--extract-html", action="store_true", help="Extract data from HTML")
    parser.add_argument("--extract-xml", action="store_true", help="Extract data from XML")

    arggroups.debug(parser)
    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=True)

    arggroups.selenium_post(args)

    return args


def _next_record_id(state, table_name):
    state["next_ids"][table_name] += 1
    return state["next_ids"][table_name]


def extract_tables(dict_, table_name, foreign_keys=False, state=None, parent_ref=None):
    if state is None:
        state = {"next_ids": defaultdict(int)}

    dict_ = objects.flatten_dict_single_parents(dict_)
    dict_ = objects.flatten_grandparents(dict_)

    tables = []
    simple_dict = {}
    child_tables = []
    for key, value in dict_.items():
        if isinstance(value, list):
            arr_ = value
            if all(isinstance(s, str) for s in arr_):
                simple_dict[key] = ", ".join(arr_)
            else:
                child_table_name = key if table_name is None else f"{table_name}_{key}"
                child_tables.append((arr_, child_table_name))
        else:
            simple_dict[key] = value

    child_table_name = child_tables[-1][1] if child_tables else None
    parent_table_name = table_name
    if parent_table_name is None and child_table_name is not None:
        parent_table_name = child_table_name + "_root"

    record_id = None
    if foreign_keys and parent_table_name is not None and simple_dict:
        record_id = simple_dict.get("id") or _next_record_id(state, parent_table_name)
        simple_dict["id"] = record_id
    if foreign_keys and parent_ref is not None and parent_table_name is not None and simple_dict:
        simple_dict[f"{parent_ref[0]}_id"] = parent_ref[1]

    for arr_, child_table_name in child_tables:
        child_parent_ref = parent_ref
        if record_id is not None:
            child_parent_ref = (parent_table_name, record_id)
        tables.extend(
            nosql_to_sql(
                arr_,
                table_name=child_table_name,
                foreign_keys=foreign_keys,
                state=state,
                parent_ref=child_parent_ref,
            )
        )

    if simple_dict:
        log.debug("simple_dict: %s", simple_dict)
        tables.append({"table_name": parent_table_name if table_name is None and child_table_name else table_name, "data": [simple_dict]})

    return tables


def _list_to_sql(dict_or_arr, table_name, foreign_keys, state, parent_ref):
    new_records = defaultdict(list)
    scalar_values = []
    for value in dict_or_arr:
        if isinstance(value, dict):
            sub_tables = extract_tables(value, table_name, foreign_keys, state, parent_ref)
            for table in sub_tables:
                new_records[table["table_name"]].extend(table["data"])
        else:
            scalar_values.append(value)

    tables = []
    if scalar_values:
        log.debug("array of scalar: %s", dict_or_arr)
        records = [{"v": value} for value in scalar_values]
        if foreign_keys and table_name is not None:
            for record in records:
                record["id"] = _next_record_id(state, table_name)
        if foreign_keys and parent_ref is not None:
            for record in records:
                record[f"{parent_ref[0]}_id"] = parent_ref[1]
        tables.append({"table_name": table_name, "data": records})

    for new_table_name, data in new_records.items():
        log.debug("array of dicts: %s", dict_or_arr)
        tables.append({"table_name": new_table_name, "data": data})
    return tables


def nosql_to_sql(dict_or_arr, table_name=None, foreign_keys=False, state=None, parent_ref=None):
    if state is None:
        state = {"next_ids": defaultdict(int)}

    if isinstance(dict_or_arr, list):
        return _list_to_sql(dict_or_arr, table_name, foreign_keys, state, parent_ref)
    if isinstance(dict_or_arr, dict):
        return extract_tables(dict_or_arr, table_name, foreign_keys, state, parent_ref)
    raise TypeError("Expected dict, list of dicts, or list of scalar values")


def _merge_soup_value(transformed, key_name, value):
    if key_name not in transformed:
        transformed[key_name] = value if isinstance(value, (dict, str)) else []
        return

    existing_value = transformed[key_name]
    if isinstance(existing_value, list):
        if isinstance(value, list):
            existing_value.extend(value)
        elif isinstance(value, (dict, str)):
            existing_value.append(value)
        return
    if isinstance(existing_value, (dict, str)):
        transformed[key_name] = [existing_value, value]
        return
    raise NotImplementedError


def _soup_tag(tag):
    tag_result = {attr: tag.attrs[attr] for attr in ("title", "href", "src", "alt") if attr in tag.attrs}
    value = soup_tree(tag.contents)
    if not isinstance(value, dict):
        message = f"Expected parsed contents for <{tag.name}> to be a dictionary, got {type(value).__name__}"
        raise TypeError(message)
    tag_result.update(value)
    return tag_result


def _soup_collection(collection):
    transformed = {}
    for element_ in collection:
        value = soup_tree(element_)
        if not value:
            continue

        element_type = type(element_)
        key_name = str(element_type.__name__)
        if element_type == element.Tag:
            key_name = element_.name
        elif isinstance(value, str):
            key_name = "text"
        _merge_soup_value(transformed, key_name, value)
    return transformed


def _soup_text(text):
    text = strings.un_paragraph(text)
    return text or None


def soup_tree(o) -> dict | str | None:
    if isinstance(o, BeautifulSoup):
        return soup_tree(o.contents)
    if isinstance(o, element.Tag):
        return _soup_tag(o)
    if isinstance(o, (element.ResultSet, list)):
        return _soup_collection(o)
    if isinstance(o, (element.Stylesheet, element.Script)):
        return None
    if isinstance(
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
        return _soup_text(o)

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

        if not (
            response and response.status_code // 100 == HTTP_SUCCESS_CLASS and "Content-Type" in response.headers
        ):  # HTTP 2xx
            return

        if response.headers["Content-Type"].startswith(("application/json",)):
            body = decode(response.body, response.headers.get("Content-Encoding", "identity"))
            body = body.decode()
            if any(s in body for s in ["searchKeywords"]):
                return

            body = strings.safe_json_loads(body)
            tables = nosql_to_sql(body, foreign_keys=True)

        elif args.extract_html and response.headers["Content-Type"].startswith(("text/html",)):
            body = decode(response.body, response.headers.get("Content-Encoding", "identity"))
            body = body.decode()

            o = html_to_dict(body)
            tables = nosql_to_sql(o, foreign_keys=True)

        elif args.extract_xml and response.headers["Content-Type"].startswith(("text/xml", "application/xml")):
            body = decode(response.body, response.headers.get("Content-Encoding", "identity"))
            body = body.decode()

            import xmltodict

            o = xmltodict.parse(body)
            tables = nosql_to_sql(o, foreign_keys=True)

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
            if args.verbose > consts.LOG_DEBUG:
                breakpoint()

            tables = db_utils.add_missing_table_names(args, tables)
            db_thread = db_utils.connect(argparse.Namespace(database=args.database, verbose=args.verbose))
            for d in tables:
                table_name = d["table_name"]
                db_thread[table_name].insert_all(iterables.list_dict_filter_bool(d["data"]), alter=True)  # type: ignore

        request = None
        response = None  # tell selenium-wire-lw to not keep the response... idk if this works

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
        for url in shell_utils.gen_paths(args):
            load_page(args, url)
    finally:
        web.quit_selenium(args)
