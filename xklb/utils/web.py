import argparse, functools, os, re, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from shutil import which

import requests

from xklb.utils import consts, db_utils, iterables, nums, path_utils, pd_utils, strings
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
        input_str or "",
    )
    if mobj is None:
        raise ValueError(f"invalid cookies from browser arguments: {input_str}")
    browser_name, keyring, profile, container = mobj.group("name", "keyring", "profile", "container")
    browser_name = browser_name.lower()
    if browser_name not in SUPPORTED_BROWSERS:
        raise ValueError(
            f'unsupported browser specified for cookies: "{browser_name}". '
            f'Supported browsers are: {", ".join(sorted(SUPPORTED_BROWSERS))}'
        )
    if keyring is not None:
        keyring = keyring.upper()
        if keyring not in SUPPORTED_KEYRINGS:
            raise ValueError(
                f'unsupported keyring specified for cookies: "{keyring}". '
                f'Supported keyrings are: {", ".join(sorted(SUPPORTED_KEYRINGS))}'
            )
    return (browser_name, profile, keyring, container)


def requests_session(args=argparse.Namespace()):
    global session  # TODO: maybe run_once similar to log_utils.log

    if session is None:
        import requests

        http_max_retries = getattr(args, "http_max_retries", None) or 5
        cookie_file = getattr(args, "cookies", None)
        cookies_from_browser = getattr(args, "cookies_from_browser", None)

        session = requests.Session()
        session.mount("http", _get_retry_adapter(http_max_retries))  # also includes https
        session.request = functools.partial(session.request, headers=headers, timeout=(4, 45))  # type: ignore

        if cookie_file or cookies_from_browser:
            from yt_dlp.cookies import load_cookies

            browser_specification = parse_cookies_from_browser(args.cookies_from_browser)
            cookie_jar = load_cookies(cookie_file, browser_specification, ydl=None)
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
                log.warning("HTTP404 Not Found: %s", url)
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

    xvfb = None
    if args.verbose < consts.LOG_DEBUG and not getattr(args, "manual", False):
        xvfb = False
        try:
            from pyvirtualdisplay.display import Display

            args.driver_display = Display(visible=False, size=(1280, 720))
            args.driver_display.start()
            xvfb = True
        except Exception:
            pass

    if which("firefox") and not getattr(args, "chrome", False):
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
    if consts.LOG_DEBUG > args.verbose and not getattr(args, "manual", False):
        try:
            args.driver_display.stop()
        except Exception:
            pass


def download_url(url, output_path=None, output_prefix=None, chunk_size=8 * 1024 * 1024, retries=3):
    session = requests_session()
    response = session.get(url, stream=True)

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
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if remote_size:
            local_size = p.stat().st_size
            if local_size == remote_size:
                log.warning(f"Download skipped. File with same size already exists: {output_path}")
                return
            elif local_size < 5242880:  # TODO: check if first few kilobytes match what already exists locally...
                p.unlink()
            else:
                headers = {"Range": f"bytes={local_size}-"}
                response = session.get(url, headers=headers, stream=True)
                if response.status_code != 206:  # HTTP Partial Content
                    p.unlink()
                    response = session.get(url, stream=True)
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
                msg = f"Download interrupted ({strings.safe_percent(downloaded_size/remote_size)}) {output_path}"
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
    session = requests_session()
    r = session.get(url, timeout=120, headers=headers)
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
