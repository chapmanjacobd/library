import argparse, datetime, functools, os, pathlib, random, re, tempfile, time, urllib.error, urllib.parse, urllib.request
from contextlib import suppress
from email.message import Message
from pathlib import Path
from shutil import which
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import bs4, requests
from idna import decode as puny_decode
from idna import encode as puny_encode

from xklb.data.http_errors import HTTPTooManyRequests, raise_for_status
from xklb.utils import consts, db_utils, iterables, nums, path_utils, pd_utils, processes, strings
from xklb.utils.log_utils import clamp_index, log

session = None


def _get_retry_adapter(args):
    import requests.adapters

    same_host_threads = getattr(args, "threads", None) or 10
    http_retries = getattr(args, "http_retries", 8)
    http_max_redirects = getattr(args, "http_max_redirects", 4)

    retry = requests.adapters.Retry(
        total=http_retries,
        connect=http_retries,
        read=http_retries // 3,
        status=http_retries // 2,
        other=1,
        redirect=http_max_redirects,
        raise_on_redirect=http_max_redirects <= 0,
        backoff_factor=3,
        backoff_jitter=2,
        backoff_max=22 * 60,
        status_forcelist=[
            104,
            413,
            429,
            500,
            502,
            503,
            504,
            522,
        ],
    )

    return requests.adapters.HTTPAdapter(max_retries=retry, pool_maxsize=same_host_threads, pool_block=True)


def parse_cookies_from_browser(input_str):
    from yt_dlp.cookies import SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS

    # lifted from yt_dlp to have a compatible interface
    container = None
    mobj = re.fullmatch(
        r"""(?x)
        (?P<name>[^+:]+)
        (?:\s*\+\s*(?P<keyring>[^:]+))?
        (?:\s*:\s*(?!:)(?P<profile>.+?))?
        (?:\s*::\s*(?P<container>.+))?
    """,
        input_str,
    )
    if mobj is None:
        msg = f"invalid cookies from browser arguments: {input_str}"
        raise ValueError(msg)
    browser_name, keyring, profile, container = mobj.group("name", "keyring", "profile", "container")
    browser_name = browser_name.lower()
    if browser_name not in SUPPORTED_BROWSERS:
        msg = (
            f'unsupported browser specified for cookies: "{browser_name}". '
            f'Supported browsers are: {", ".join(sorted(SUPPORTED_BROWSERS))}'
        )
        raise ValueError(msg)
    if keyring is not None:
        keyring = keyring.upper()
        if keyring not in SUPPORTED_KEYRINGS:
            msg = (
                f'unsupported keyring specified for cookies: "{keyring}". '
                f'Supported keyrings are: {", ".join(sorted(SUPPORTED_KEYRINGS))}'
            )
            raise ValueError(msg)
    return (browser_name, profile, keyring, container)


def requests_session(args=argparse.Namespace()):
    global session

    from yt_dlp.utils.networking import std_headers

    if session is None:
        import requests

        cookie_file = getattr(args, "cookies", None)
        cookies_from_browser = getattr(args, "cookies_from_browser", None)

        max_redirects = getattr(args, "http_max_redirects", 4)

        session = requests.Session()
        session.mount("http://", _get_retry_adapter(args))
        session.mount("https://", _get_retry_adapter(args))

        std_params = {"headers": std_headers, "timeout": consts.REQUESTS_TIMEOUT, "allow_redirects": max_redirects > 0}
        session.request = functools.partial(session.request, **std_params)
        session.get = functools.partial(session.get, **std_params)

        if getattr(args, "allow_insecure", False):
            from urllib3.exceptions import InsecureRequestWarning

            requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)  # type: ignore
            session.verify = False

        if cookie_file or cookies_from_browser:
            from yt_dlp.cookies import load_cookies

            if cookies_from_browser:
                cookies_from_browser = parse_cookies_from_browser(cookies_from_browser)
            cookie_jar = load_cookies(cookie_file, cookies_from_browser, ydl=None)
            session.cookies = cookie_jar  # type: ignore

    return session


def get(args, url, skip_404=True, ignore_errors=False, ignore_429=False, **kwargs):
    s = requests_session(args)
    try:
        response = s.get(url, **kwargs)
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
        requests.exceptions.ContentDecodingError,
        requests.exceptions.RequestException,
    ):
        raise
    else:
        code = response.status_code

        if 200 <= code < 400:
            return response
        elif code == 404:
            if skip_404:
                log.warning("404 Not Found: %s", url)
                return None
            else:
                raise FileNotFoundError
        elif ignore_errors and (400 <= code < 429 or 431 <= code < 500):
            return response
        elif ignore_429 and (400 <= code < 500):
            return response
        else:
            response.raise_for_status()

    log.info("Something weird is happening probably: %s", url)
    return response


class PartialContent:
    def __init__(self, url, max_size=1048576):
        self.url = url
        self.max_size = max_size
        self.temp_file = None

    def __enter__(self):
        assert session is not None

        try:
            with (
                processes.timeout_thread(max(consts.REQUESTS_TIMEOUT) + 5),
                session.get(self.url, stream=True) as r,
            ):
                code = r.status_code
                if code == 404:
                    log.warning("404 Not Found: %s", self.url)
                    return None
                else:
                    r.raise_for_status()

                self.temp_file = tempfile.NamedTemporaryFile(delete=False)

                for chunk in r.iter_content(chunk_size=65536):
                    if self.temp_file.tell() < self.max_size:
                        self.temp_file.write(chunk)
                    else:
                        break

            self.temp_file.close()
            return self.temp_file.name
        except TimeoutError:
            return None

    def __exit__(self, exc_type, exc_value, traceback):
        if self.temp_file:
            os.remove(self.temp_file.name)


def download_embeds(args, soup):
    for img in soup.find_all("img"):
        local_path = Path.cwd() / "images"
        local_path.mkdir(exist_ok=True)
        local_path = local_path / Path(urllib.parse.unquote(img["src"])).name

        response = get(args, img["src"])
        if response:
            with open(local_path, "wb") as f:
                f.write(response.content)

            img["src"] = local_path.relative_to(Path.cwd())  # Update image source to point to local file


def find_date(soup):
    import dateutil.parser

    for text in soup.find_all(string=True):
        try:
            date = dateutil.parser.parse(text)
            return date
        except ValueError:
            pass
    return None


def set_timestamp(headers, path):
    if "Last-Modified" in headers:
        modified_time = (
            datetime.datetime.strptime(headers["Last-Modified"], "%a, %d %b %Y %H:%M:%S GMT")
            .replace(tzinfo=ZoneInfo("GMT"))
            .astimezone()
        )
        mtime = time.mktime(modified_time.timetuple())
        atime = time.time()
        os.utime(path, (atime, mtime))


def load_selenium(args, wire=False):
    if getattr(args, "driver", False):
        return

    if wire:
        import logging

        from seleniumwire import webdriver

        log_levels = [logging.ERROR, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG]
        for logger_name in logging.root.manager.loggerDict.keys():
            if logger_name.startswith("selenium"):
                logging.getLogger(logger_name).setLevel(clamp_index(log_levels, args.verbose - 1))

    else:
        from selenium import webdriver

    xvfb = None  # three states
    if args.verbose < consts.LOG_DEBUG and not getattr(args, "manual", False):
        xvfb = False
        with suppress(Exception):
            from pyvirtualdisplay.display import Display

            args.driver_display = Display(visible=False, size=(1280, 720))
            args.driver_display.start()
            xvfb = True

    if (which("firefox") or which("firefox.exe") or getattr(args, "firefox", False)) and not getattr(
        args, "chrome", False
    ):
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service

        service = Service(log_path=tempfile.mktemp(".geckodriver.log"))
        options = Options()
        if Path("selenium").exists():
            options.profile = "selenium"

        options.set_preference("media.volume_scale", "0.0")
        if xvfb is False:
            options.add_argument("--headless")

        args.driver = webdriver.Firefox(service=service, options=options)

        addons = [Path("~/.local/lib/ublock_origin.xpi").expanduser().resolve()]
        if getattr(args, "auto_pager", False):
            addons.append(Path("~/.local/lib/weautopagerize.xpi").expanduser().resolve())

        for addon_path in addons:
            try:
                args.driver.install_addon(str(addon_path))
            except Exception:
                if args.verbose > 0:
                    log.warning("Could not install firefox addon. Missing file %s", addon_path)
                else:
                    log.exception("Could not install firefox addon. Missing file %s", addon_path)

        if getattr(args, "auto_pager", False):
            time.sleep(60)  # let auto-pager initialize

    else:
        from selenium.webdriver.chrome.options import Options

        options = Options()
        if Path("selenium").exists():
            options.add_argument("user-data-dir=selenium")

        options.add_argument("--mute-audio")
        if xvfb is False:
            options.add_argument("--headless=new")

        addons = [Path("~/.local/lib/ublock_origin.crx").expanduser().resolve()]
        if getattr(args, "auto_pager", False):
            addons.append(Path("~/.local/lib/autopager.crx").expanduser().resolve())
        for addon_path in addons:
            try:
                options.add_extension(str(addon_path))
            except Exception:
                if args.verbose > 0:
                    log.warning("Could not install chrome extension. Missing file %s", addon_path)
                else:
                    log.exception("Could not install chrome extension. Missing file %s", addon_path)

        args.driver = webdriver.Chrome(options=options)


def quit_selenium(args):
    args.driver.quit()
    if args.verbose < consts.LOG_DEBUG and not getattr(args, "manual", False):
        with suppress(Exception):
            args.driver_display.stop()


def post_download(args):
    min_sleep_interval = getattr(args, "sleep_interval", None) or 0
    sleep_interval = random.uniform(min_sleep_interval, getattr(args, "max_sleep_interval", None) or min_sleep_interval)
    if sleep_interval > 0:
        log.debug("[download] Sleeping %s seconds ...", sleep_interval)
        time.sleep(sleep_interval)


def safe_unquote(url):
    # https://en.wikipedia.org/wiki/Internationalized_Resource_Identifier
    # we aren't writing HTML so we can unquote

    try:
        parsed_url = urlparse(url)
    except UnicodeDecodeError:
        return url

    def selective_unquote(component, restricted_chars):
        try:
            unquoted = unquote(component, errors="strict")
        except UnicodeDecodeError:
            return component
        # re-quote restricted chars
        return "".join(quote(char, safe="") if char in restricted_chars else char for char in unquoted)

    def unquote_query_params(query):
        query_pairs = parse_qsl(query, keep_blank_values=True)
        return "&".join(
            selective_unquote(key, "=&#") + "=" + selective_unquote(value, "=&#") for key, value in query_pairs
        )

    unquoted_path = selective_unquote(parsed_url.path, ";?#")
    unquoted_params = selective_unquote(parsed_url.params, "?#")
    unquoted_query = unquote_query_params(parsed_url.query)
    unquoted_fragment = selective_unquote(parsed_url.fragment, "")

    new_url = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, unquoted_path, unquoted_params, unquoted_query, unquoted_fragment)
    )

    return new_url


def url_decode(href):
    href = safe_unquote(href)
    up = urlparse(href)
    if up.netloc:
        with suppress(Exception):
            href = href.replace(up.netloc, puny_decode(up.netloc), 1)
    return href


def path_tuple_from_url(url):
    url = url_decode(url)
    parsed_url = urlparse(url)
    relative_path = os.path.join(parsed_url.netloc, parsed_url.path.lstrip("/"))
    parent_path = os.path.dirname(relative_path)
    filename = path_utils.basename(parsed_url.path)
    return parent_path, filename


def filename_from_content_disposition(response):
    content_disposition = response.headers.get("Content-Disposition", "")
    if "filename=" in content_disposition:
        msg = Message()
        msg["content-disposition"] = content_disposition
        filename = msg.get_filename()
        if filename:
            return filename
    return None


def url_to_local_path(url, response=None, output_path=None, output_prefix=None):
    dir_path, filename = path_tuple_from_url(url)

    if response:
        filename_from_site = filename_from_content_disposition(response)
        if filename_from_site:
            filename = filename_from_site

    if not output_path:
        output_path = filename
        if dir_path:
            output_path = os.path.join(dir_path, filename)

    output_path = path_utils.clean_path(output_path.encode())

    if output_prefix:
        output_path = os.path.join(output_prefix, output_path)

    return output_path


def download_url(args, url: str, output_path=None, retry_num=0) -> str | None:
    global session
    if session is None:
        log.warning("Creating new web.session")
        session = requests_session()

    if retry_num > args.http_download_retries:
        msg = f"Max retries exceeded for {url}"
        raise RuntimeError(msg)

    log.debug("Downloading file %s retry %s", url, retry_num)
    try:
        r = session.get(url, stream=True)
        if not 200 <= r.status_code < 400:
            log.error(f"Error {r.status_code} {url}")
            raise_for_status(r.status_code)

        remote_size = nums.safe_int(r.headers.get("Content-Length"))

        output_path = url_to_local_path(url, response=r, output_path=output_path, output_prefix=args.prefix)
        if output_path == ".":
            log.warning("Skipping directory %s", url)
            return None

        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            if remote_size:
                local_size = p.stat().st_size
                if local_size == remote_size:
                    log.warning(f"Skipped download. File with same size already exists: {output_path}")
                    post_download(args)
                    return output_path
                elif local_size < 5242880:  # TODO: check if first few kilobytes match what already exists locally...
                    p.unlink()
                else:
                    log.warning(
                        f"Resuming download. {strings.file_size(local_size)} => {strings.file_size(remote_size)} ({strings.safe_percent(local_size/remote_size)}): {output_path}"
                    )
                    headers = {"Range": f"bytes={local_size}-"}
                    r.close()  # close previous session before opening a new one
                    r = session.get(url, headers=headers, stream=True)
                    if r.status_code != 206:  # HTTP Partial Content
                        p.unlink()
                        r.close()  # close previous session before opening a new one
                        r = session.get(url, stream=True)
            else:
                p.unlink()
        else:
            log.info("Writing %s \n\tto %s", url, output_path)

        try:
            with open(output_path, "ab") as f:
                for chunk in r.iter_content(chunk_size=args.download_chunk_size):
                    if chunk:
                        f.write(chunk)

            if remote_size:
                downloaded_size = os.path.getsize(output_path)
                if downloaded_size < remote_size:
                    msg = f"Incomplete download ({strings.safe_percent(downloaded_size/remote_size)}) {output_path}"
                    raise RuntimeError(msg)
        except Exception as e:
            r.close()
            if isinstance(e, HTTPTooManyRequests):
                raise
            if isinstance(e, OSError) and e.errno in consts.EnvironmentErrors:
                raise
            retry_num += 1
            log.debug("Retry #%s %s", retry_num, url)
            time.sleep(retry_num)
            return download_url(args, url, output_path, retry_num)

        set_timestamp(r.headers, output_path)
    finally:
        if "r" in locals():  # prevent UnboundLocalError
            r.close()

    post_download(args)
    return output_path


def get_elements_forward(start, end):
    elements = []
    current_tag = start.next_sibling
    while current_tag and current_tag != end:
        if isinstance(current_tag, bs4.NavigableString):
            elements.append(current_tag)
        current_tag = current_tag.next_element
    return elements


def extract_nearby_text(a_element, delimiter):
    prev_a = a_element.find_previous(delimiter)
    next_a = a_element.find_next(delimiter)

    before = ""
    if prev_a:
        before = " ".join(s.get_text(strip=True) for s in get_elements_forward(prev_a, a_element))

    after = ""
    if next_a:
        after = " ".join(s.get_text(strip=True) for s in get_elements_forward(a_element, next_a))

    return before, after


def tags_with_text(soup, delimit_fn):
    tags = soup.find_all(delimit_fn)

    for i, tag in enumerate(tags):
        before_text = []
        after_text = []

        if i == 0:
            current_tag = tag.previous_element
            while current_tag and current_tag != tag:
                if isinstance(current_tag, bs4.NavigableString):
                    text = strings.un_paragraph(current_tag.get_text()).strip()
                    if text and text not in before_text:
                        before_text.append(text)
                current_tag = current_tag.previous_element
            before_text.reverse()

        current_tag = tag.next_sibling
        while current_tag and (i == len(tags) - 1 or current_tag != tags[i + 1]):  # end tag or until next tag
            if isinstance(current_tag, bs4.NavigableString):
                text = strings.un_paragraph(current_tag.get_text()).strip()
                if text and text not in after_text:
                    after_text.append(text)
            current_tag = current_tag.next_element

        tag.before_text = "\n".join(before_text).strip()
        tag.after_text = "\n".join(after_text).strip()

    return tags


def save_html_table(args, html_file):
    import pandas as pd

    dfs = pd.read_html(html_file, extract_links="body", flavor="bs4")
    tables = []
    for df in dfs:
        df = pd_utils.columns_snake_case(df)

        # extract URLs into their own columns
        for col in df.columns:
            if df[col].dtype == "object":
                df[[col, f"{col}_url"]] = pd.DataFrame(df[col].tolist(), index=df.index)
        df.columns = df.columns.astype(str)
        df = df.dropna(axis=1, how="all")  # drop empty columns

        df = pd_utils.convert_dtypes(df)

        tables.append({"table_name": None, "data": df.to_dict(orient="records")})

    tables = db_utils.add_missing_table_names(args, tables)
    for d in tables:
        args.db[d["table_name"]].insert_all(iterables.list_dict_filter_bool(d["data"]), alter=True)


def re_trigger_input(driver):
    from selenium.common.exceptions import NoSuchElementException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    input_field = None
    for by, name in [
        (By.NAME, "q"),
        (By.NAME, "query"),
        (By.CSS_SELECTOR, "input[type='search']"),
        (By.NAME, "search"),
        (By.NAME, "search-input"),
        (By.NAME, "search-query"),
        (By.NAME, "search-box"),
        (By.ID, "q"),
        (By.ID, "query"),
        (By.ID, "search"),
        (By.ID, "search-input"),
        (By.ID, "search-query"),
        (By.ID, "search-input"),
        (By.ID, "search-box"),
        (By.CLASS_NAME, "q"),
        (By.CLASS_NAME, "query"),
        (By.CLASS_NAME, "search"),
        (By.CLASS_NAME, "search-input"),
        (By.CLASS_NAME, "search-query"),
        (By.CLASS_NAME, "search-input"),
        (By.CLASS_NAME, "search-box"),
        (By.TAG_NAME, "input"),
    ]:
        try:
            input_field = driver.find_element(by, name)
            break
        except NoSuchElementException:
            pass

    if input_field is None:
        return
    else:
        input_field.send_keys(Keys.RETURN)
        driver.implicitly_wait(8)


def selenium_get_page(args, url):
    args.driver.get(url)
    args.driver.implicitly_wait(5)

    if getattr(args, "poke", False):
        re_trigger_input(args.driver)


def scroll_down(driver):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)
    new_height = driver.execute_script("return document.body.scrollHeight")
    return new_height


def extract_html(url) -> str:
    from yt_dlp.utils.networking import std_headers

    session = requests_session()
    r = session.get(url, timeout=120, headers=std_headers)
    r.raise_for_status()
    markup = r.text
    return markup


def selenium_extract_html(driver) -> str:
    # trigger rollover events
    driver.execute_script(
        "(function(){function k(x) { if (x.onmouseover) { x.onmouseover(); x.backupmouseover = x.onmouseover; x.backupmouseout = x.onmouseout; x.onmouseover = null; x.onmouseout = null; } else if (x.backupmouseover) { x.onmouseover = x.backupmouseover; x.onmouseout = x.backupmouseout; x.onmouseover(); x.onmouseout(); } } var i,x; for(i=0; x=document.links[i]; ++i) k(x); for (i=0; x=document.images[i]; ++i) k(x); })()"
    )

    # include Shadow DOM
    html_text = driver.execute_script(
        'function s(n=document.body){if(!n)return"";if(n.nodeType===Node.TEXT_NODE)return n.textContent.trim();if(n.nodeType!==Node.ELEMENT_NODE)return"";let t="";let r=n.cloneNode();n=n.shadowRoot||n;if(n.children.length)for(let o of n.childNodes)if(o.assignedNodes){if(o.assignedNodes()[0])t+=s(o.assignedNodes()[0]);else t+=o.innerHTML}else t+=s(o);else t=n.innerHTML;return r.innerHTML=t,r.outerHTML}; return s()'
    )

    return html_text


def infinite_scroll(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        new_height = scroll_down(driver)
        yield selenium_extract_html(driver)

        if new_height == last_height:  # last page
            time.sleep(5)  # try once more in case slow page
            new_height = scroll_down(driver)
            if new_height == last_height:
                break
        last_height = new_height

    yield selenium_extract_html(driver)


def construct_search(engine, s):
    s = urllib.parse.quote(s, safe="")
    return engine.replace("%", s, 1)


def construct_absolute_url(base_url, href):
    up = urlparse(href)
    if up.scheme and up.scheme not in ("https", "http", "ftp"):
        return href

    if not up.netloc:
        if not base_url.endswith("/") and not href.startswith("/"):
            base_url += "/"

        href = urljoin(base_url, href)

    if href.startswith("//"):
        href = "https:" + href

    return href


def is_index(url):
    if url.endswith("/"):
        return True

    patterns = [
        r"/index\.php\?dir=",
        r"/index\.php$",
        r"/index\.html?$",
    ]
    for pattern in patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True

    return False


def remove_apache_sorting_params(url):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    apache_sorting_keys = ["C", "O"]
    for key in apache_sorting_keys:
        query_params.pop(key, None)
    new_query_string = urlencode(query_params, doseq=True)

    new_url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query_string,
            parsed_url.fragment,
        )
    )

    return new_url


def sleep(args, secs=0):
    sleep_interval = getattr(args, "sleep_interval_requests", None) or secs
    if sleep_interval > 0:
        log.debug("Sleeping %s seconds ...", sleep_interval)
        time.sleep(sleep_interval)


def safe_quote(url):
    try:
        parsed_url = urlparse(url)
    except UnicodeDecodeError:
        return url

    def selective_quote(component, restricted_chars):
        try:
            quoted = quote(component, errors="strict")
        except UnicodeDecodeError:
            return component
        return "".join(quote(char, safe="%") if char in restricted_chars else char for char in quoted)

    def quote_query_params(query):
        query_pairs = parse_qsl(query, keep_blank_values=True)
        return "&".join(selective_quote(key, "=&#") + "=" + selective_quote(value, "=&#") for key, value in query_pairs)

    quoted_path = selective_quote(parsed_url.path, ";?#")
    quoted_params = selective_quote(parsed_url.params, "?#")
    quoted_query = quote_query_params(parsed_url.query)
    quoted_fragment = selective_quote(parsed_url.fragment, "")

    new_url = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, quoted_path, quoted_params, quoted_query, quoted_fragment)
    )

    return new_url


def url_encode(href):
    href = safe_quote(href)
    up = urlparse(href)
    if up.netloc:
        with suppress(Exception):
            href = href.replace(up.netloc, puny_encode(up.netloc).decode(), 1)
    return href


def is_subpath(parent_url, child_url):
    child = urlparse(child_url)
    parent = urlparse(parent_url)

    if child.scheme != parent.scheme or child.netloc != parent.netloc:
        return False

    return child_url.startswith(parent_url)


def is_html(url, max_size=15 * 1024 * 1024):
    with requests_session().get(url, stream=True) as r:
        content_length = r.headers.get("Content-Length")
    if content_length and int(content_length) > max_size:
        return False

    content_type = r.headers.get("Content-Type")
    if content_type and not any(
        s in content_type for s in ("text/html", "text/xhtml", "text/xml", "application/xml", "application/xhtml+xml")
    ):
        return False

    try:
        chunk = next(r.iter_content(max_size + 1))  # one more byte than max_size
        if len(chunk) > max_size:
            return False
    except (requests.RequestException, StopIteration):
        return False

    return True  # if ambiguous, return True


def fake_title(url):
    p = urllib.parse.urlparse(url)
    title = f"{p.netloc} {p.path} {p.params} {p.query}: {p.fragment}"

    if title.startswith("www."):
        title = title[4:]

    title = title.replace("/", " ")
    title = title.replace("?", " ")
    title = title.replace("#", ": ")

    return title.strip()


def get_title(args, url):
    global session
    if session is None:
        log.warning("Creating new web.session")
        session = requests_session()

    import requests.exceptions
    from bs4 import BeautifulSoup

    try:
        if getattr(args, "local_html", False):
            with open(url) as f:
                html_text = f.read()
            url = "file://" + url
        elif args.selenium:
            selenium_get_page(args, url)
            html_text = args.driver.page_source
        else:
            html_text = session.get(url).text

        soup = BeautifulSoup(html_text, "lxml")
        title = soup.title.text.strip() if soup.title else url
    except requests.exceptions.RequestException as e:
        title = fake_title(url)

    sleep(args)

    return title


class WebStatResult:
    def __init__(self, response):
        self.st_size = nums.safe_int(response.headers.get("Content-Length")) or 0
        self.st_atime = consts.now()
        self.st_mtime = (
            nums.safe_int(
                datetime.datetime.strptime(
                    response.headers.get("Last-Modified"), "%a, %d %b %Y %H:%M:%S %Z"
                ).timestamp()
                if response.headers.get("Last-Modified")
                else None
            )
            or consts.now()
        )


class WebPath:
    def __new__(cls, *args):
        if args and str(args[0]).startswith("http"):
            return object.__new__(cls)
        return pathlib.Path(*args)

    def __init__(self, path):
        self._path = str(path)

    def __fspath__(self):
        return str(self)

    @property
    def parent(self):
        scheme, netloc, path, params, query, fragment = urlparse(str(self))

        if fragment:
            fragments = fragment.rstrip("&").rsplit("&", 1)
            fragment = "" if len(fragments) == 1 else fragments[0]
        elif query:
            queries = query.rstrip("&").rsplit("&", 1)
            query = "" if len(queries) == 1 else queries[0]
        elif params:
            parameters = params.rstrip("&").rsplit("&", 1)
            params = "" if len(parameters) == 1 else parameters[0]
        elif path:
            paths = path.rstrip("/").rsplit("/", 1)
            path = "" if len(paths) == 1 else paths[0]

        return WebPath(urlunparse((scheme, netloc, path, params, query, fragment)))

    @property
    def parts(self):
        res = urlparse(str(self))
        parts = []
        if res.scheme:
            parts += [res.scheme]
        if res.netloc:
            parts += [res.netloc]
        if res.path:
            parts += "/".split(res.path)
        if res.params:
            parts += "&".split(res.params)
        if res.query:
            parts += "&".split(res.query)
        if res.fragment:
            parts += "&".split(res.fragment)
        return tuple(parts)

    @processes.with_timeout_thread(max(consts.REQUESTS_TIMEOUT) + 5)
    def head(self, follow_symlinks=True):
        if self._head:
            return self._head

        global session
        if session is None:
            log.warning("Creating new web.session")
            session = requests_session()

        self._head = session.head(str(self), allow_redirects=follow_symlinks)
        return self._head

    def stat(self, follow_symlinks=True):
        r = self.head(follow_symlinks=follow_symlinks)

        if 200 <= r.status_code < 400:
            pass
        elif r.status_code == 404:
            raise FileNotFoundError
        else:
            r.raise_for_status()

        return WebStatResult(r)

    def exists(self, *, follow_symlinks=True):
        try:
            self.stat(follow_symlinks=follow_symlinks)
        except FileNotFoundError:
            return False
        return True

    def unlink(self):
        pass

    def as_posix(self) -> str:
        return os.path.join(*path_tuple_from_url(str(self)))

    def remote_name(self):
        return filename_from_content_disposition(self.head())

    def __truediv__(self, other):
        return WebPath(f"{str(self)}/{str(other)}")

    def __str__(self):
        return self._path


@processes.with_timeout_thread(max(consts.REQUESTS_TIMEOUT) + 5)
def stat(url, follow_symlinks=True):
    global session
    if session is None:
        log.warning("Creating new web.session")
        session = requests_session()

    r = session.head(url, allow_redirects=follow_symlinks)

    if 200 <= r.status_code < 400:
        pass
    elif r.status_code == 404:
        raise FileNotFoundError
    else:
        r.raise_for_status()

    return WebStatResult(r)


def gen_output_path(args, path, target_extension):
    output_path = Path(url_to_local_path(path) if str(path).startswith("http") else path)
    if args.clean_path:
        before = output_path
        output_path = Path(path_utils.clean_path(os.fsencode(output_path), max_name_len=255 - len(target_extension)))
        if before != output_path:
            log.warning("Output folder will be different due to path cleaning: %s", Path(output_path).parent)
    output_path = Path(output_path).with_suffix(target_extension)
    return output_path
