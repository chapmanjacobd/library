import functools, os, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from shutil import which

from xklb.utils import consts, db_utils, iterables, nums, path_utils, pd_utils
from xklb.utils.log_utils import clamp_index, log

headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0"}
session = None


def _get_retry_adapter(max_retries):
    import requests.adapters, urllib3.util.retry

    retries = urllib3.util.retry.Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=2,
        redirect=False,  # don't fail on redirect
        backoff_factor=5,
        status_forcelist=[
            413,
            429,
            500,
            502,
            503,
            504,
        ],
    )

    return requests.adapters.HTTPAdapter(max_retries=retries)


def requests_session(max_retries=5):
    global session

    if session is None:
        import requests

        session = requests.Session()
        session.mount("http", _get_retry_adapter(max_retries))  # also includes https
        session.request = functools.partial(session.request, timeout=(4, 45))  # type: ignore

    return session


class ChocolateChip:
    def __init__(self, args):
        from yt_dlp.cookies import load_cookies
        from yt_dlp.utils import YoutubeDLCookieProcessor  # type: ignore

        if args.cookies_from_browser:
            args.cookies_from_browser = (args.cookies_from_browser,)
        cookiejar = load_cookies(args.cookies, args.cookies_from_browser, ydl=None)
        cookie_processor = YoutubeDLCookieProcessor(cookiejar)
        self.opener = urllib.request.build_opener(cookie_processor)

    def get(self, url):
        request = urllib.request.Request(url)
        response = self.opener.open(request, timeout=60)
        response_data = response.read()
        if response.getcode() != 200:
            raise urllib.error.HTTPError(url, response.getcode(), response_data, response.headers, None)
        response.close()
        return response_data


def requests_authed_get(args, url) -> bytes:
    if args.cookies or args.cookies_from_browser:
        if not hasattr(args, "authed_web"):
            args.authed_web = ChocolateChip(args)
        return args.authed_web.get(url)
    else:
        response = requests_session().get(url, timeout=60)
        response.raise_for_status()
        return response.content


def download_embeds(args, soup):
    for img in soup.find_all("img"):
        local_path = Path.cwd() / "images"
        local_path.mkdir(exist_ok=True)
        local_path = local_path / Path(urllib.parse.unquote(img["src"])).name

        data = requests_authed_get(args, img["src"])
        with open(local_path, "wb") as f:
            f.write(data)

        img["src"] = local_path.relative_to(Path.cwd())  # Update image source to point to local file


def find_date(soup):
    import dateutil.parser

    for text in soup.find_all(text=True):
        try:
            date = dateutil.parser.parse(text)
            return date
        except ValueError:
            pass
    return None


def load_selenium(args, wire=False):
    if wire:
        import logging

        from seleniumwire import webdriver

        log_levels = [logging.ERROR, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG]
        for logger_name, logger in logging.root.manager.loggerDict.items():
            if logger_name.startswith("selenium"):
                logging.getLogger(logger_name).setLevel(clamp_index(log_levels, args.verbose - 1))

    else:
        from selenium import webdriver

    if args.verbose < consts.LOG_DEBUG:
        from pyvirtualdisplay.display import Display

        args.driver_display = Display(visible=False, size=(1280, 720))
        args.driver_display.start()

    if which("firefox"):
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service

        service = Service(log_path=tempfile.mktemp(".geckodriver.log"))
        options = Options()
        options.set_preference("media.volume_scale", "0.0")
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
        args.driver = webdriver.Chrome()


def quit_selenium(args):
    args.driver.quit()
    if consts.LOG_DEBUG > args.verbose:
        args.driver_display.stop()


def wait_selenium_close(args):
    from selenium.common.exceptions import InvalidSessionIdException

    while True:
        try:
            _ = args.driver.window_handles
        except InvalidSessionIdException:
            break
        time.sleep(1)


def download_url(url, output_path=None, output_prefix=None, chunk_size=8 * 1024 * 1024, retries=3):
    response = requests_session().get(url, stream=True)

    if response.status_code // 100 != 2:  # Not 2xx
        log.error(f"Error {response.status_code} downloading {url}")

    remote_size = nums.safe_int(response.headers.get("Content-Length"))

    if output_path is None:
        content_d = response.headers.get("Content-Disposition")
        if content_d:
            output_path = content_d.split("filename=")[1].replace("/", "-")
        else:
            output_path = url.split("/")[-1]

        if output_prefix:
            output_path = os.path.join(output_prefix / output_path)
        output_path = path_utils.clean_path(output_path.encode())

    p = Path(output_path)
    if p.exists():
        if remote_size:
            local_size = p.stat().st_size
            if local_size == remote_size:
                log.warning(f"Download skipped. File with same size already exists: {output_path}")
                return
            else:
                headers = {"Range": f"bytes={local_size}-"}
                response = requests_session().get(url, headers=headers, stream=True)
                if response.status_code != 206:  # HTTP Partial Content
                    p.unlink()
                    response = requests_session().get(url, stream=True)
        else:
            p.unlink()

    with open(output_path, "ab") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)

    if remote_size:
        downloaded_size = os.path.getsize(output_path)
        if downloaded_size < remote_size:
            if retries <= 0:
                msg = f"Download interrupted ({downloaded_size/remote_size:.1%}) {output_path}"
                raise RuntimeError(msg)
            else:
                download_url(url, output_path, output_prefix, chunk_size, retries=retries - 1)


def get_elements_forward(start, end):
    elements = []
    current = start.next_sibling
    while current and current != end:
        elements.append(current)
        current = current.next_sibling
    return elements


def extract_nearby_text(a_element):
    prev_a = a_element.find_previous("a")
    next_a = a_element.find_next("a")

    before = ""
    if prev_a:
        before = " ".join(s.get_text(strip=True) for s in get_elements_forward(prev_a, a_element))

    after = ""
    if next_a:
        after = " ".join(s.get_text(strip=True) for s in get_elements_forward(a_element, next_a))

    return before, after


def save_html_table(args, html_file):
    import pandas as pd

    dfs = pd.read_html(html_file, extract_links="body", flavor="bs4")
    tables = []
    for df in dfs:
        df = pd_utils.columns_snake_case(df)

        # extract URLs into their own columns
        for col in df.columns:
            if df[col].dtype == "object":
                df[[col, col + "_url"]] = pd.DataFrame(df[col].tolist(), index=df.index)
        df = df.dropna(axis=1, how="all")  # drop empty columns

        for col in df.columns:
            try:
                df.loc[:, col] = df[col].str.replace(",", "").astype(float)
            except ValueError:
                continue  # column was not numeric after all (•́⍜•̀), skip
        df = df.convert_dtypes()

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


def extract_html_text(driver):
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
        yield extract_html_text(driver)

        if new_height == last_height:  # last page
            time.sleep(5)  # try once more in case slow page
            new_height = scroll_down(driver)
            if new_height == last_height:
                break
        last_height = new_height

    yield extract_html_text(driver)
