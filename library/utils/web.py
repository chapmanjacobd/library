import argparse, datetime, functools, http.cookiejar, os, pathlib, random, re, shutil, socket, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, warnings
from contextlib import suppress
from email.message import Message
from pathlib import Path
from shutil import which
from urllib.parse import parse_qs, parse_qsl, quote, urldefrag, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import bs4, requests, urllib3
from bs4 import element
from idna import encode as puny_encode

from library.data.http_errors import (
    HTTPStatus,
    HTTPTooManyRequests,
    RecoverableError,
    UnrecoverableError,
    raise_for_status,
)
from library.utils import consts, db_utils, iterables, nums, path_utils, pd_utils, printing, processes, strings
from library.utils.log_utils import clamp_index, log
from library.utils.path_utils import path_tuple_from_url

warnings.filterwarnings("ignore", category=bs4.XMLParsedAsHTMLWarning)

HTML_MIME_TYPES = ("text/html", "text/xhtml", "application/xhtml+xml")
XML_MIME_TYPES = ("text/xml", "application/xml")
INTERNET_ARCHIVE_NO_RETRIES = -1

session = None
cookie_jar = None
internetarchive = None
cdx_toolkit = None


def _get_retry_adapter(args):
    import requests.adapters

    same_host_threads = getattr(args, "threads", None) or 10
    retry = _get_retry(args)

    return requests.adapters.HTTPAdapter(max_retries=retry, pool_maxsize=same_host_threads, pool_block=True)


def _get_retry(args):
    import requests.adapters

    http_retries = getattr(args, "http_retries", 8)
    http_max_redirects = getattr(args, "http_max_redirects", 4)

    return requests.adapters.Retry(
        total=http_retries,
        connect=http_retries,
        read=http_retries,
        status=http_retries // 2,
        other=http_retries // 3,
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


def _get_internet_archive_session(args):
    from internetarchive.session import ArchiveSession

    retry = _get_retry(args)

    class LibraryArchiveSession(ArchiveSession):
        def mount_http_adapter(self, protocol=None, max_retries=None, status_forcelist=None, host=None):
            if isinstance(max_retries, (int, float)):
                max_retries = retry
            return super().mount_http_adapter(protocol, max_retries, status_forcelist, host)

    return LibraryArchiveSession(http_adapter_kwargs={"max_retries": retry})


def _is_internet_archive_flag(value) -> bool:
    return str(value).lower() in {"1", "true", "yes"}


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


def load_cookie_jar(args):
    global cookie_jar

    if cookie_jar is None:
        cookie_file = getattr(args, "cookies", None)
        cookies_from_browser = getattr(args, "cookies_from_browser", None)

        if cookie_file or cookies_from_browser:
            from yt_dlp.cookies import load_cookies

            if cookies_from_browser:
                cookies_from_browser = parse_cookies_from_browser(cookies_from_browser)
            cookie_jar = load_cookies(cookie_file, cookies_from_browser, ydl=None)

    return cookie_jar


def requests_session(args=argparse.Namespace()):
    global session, cookie_jar
    load_cookie_jar(args)

    from yt_dlp.utils.networking import std_headers

    if session is None:
        import requests

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

        if cookie_jar:
            session.cookies = cookie_jar  # type: ignore

    return session


def get(args, url, skip_404=True, ignore_errors=False, ignore_429=False, **kwargs):
    s = requests_session(args)
    try:
        response = s.get(url, **kwargs)
    except (ConnectionError, requests.exceptions.SSLError) as excinfo:
        log.error("%s %s", url, excinfo)
    except (
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
        requests.exceptions.ContentDecodingError,
        requests.exceptions.RequestException,
    ):
        raise
    else:
        code = HTTPStatus(response.status_code)

        if code.is_informational or code.is_success:
            return response
        elif code == HTTPStatus.NOT_FOUND:
            if skip_404:
                log.warning("404 Not Found: %s", url)
                return None
            else:
                raise FileNotFoundError
        elif code.is_redirection:
            # requests redirects exceeded
            response.raise_for_status()
        elif code.is_client_error:
            if code == HTTPStatus.TOO_MANY_REQUESTS:
                if ignore_429:
                    return response
            elif ignore_errors:  # ignore all except 429
                return response

            response.raise_for_status()
        elif code.is_server_error:
            response.raise_for_status()

    log.info("Something weird is happening probably: %s", url)
    raise RuntimeError


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
            os.unlink(self.temp_file.name)


def download_embeds(args, soup):
    for img in soup.find_all("img"):
        local_path = Path.cwd() / "images"
        local_path.mkdir(exist_ok=True)
        local_path = local_path / Path(urllib.parse.unquote(img["src"])).name

        response = get(args, img["src"])
        if response:
            Path(local_path).write_bytes(response.content)

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


def get_browser_profile_path(browser_name, profile=None):
    from yt_dlp.cookies import _firefox_browser_dirs, _get_chromium_based_browser_settings

    browser_name = browser_name.lower()

    if browser_name == "firefox":
        profile_roots = [root for root in _firefox_browser_dirs() if os.path.isfile(os.path.join(root, "profiles.ini"))]
        if not profile_roots:
            return None
        root = profile_roots[0]
        if profile:
            candidate = os.path.join(root, profile)
            if os.path.isdir(candidate):
                return candidate
        default_profile = _firefox_default_profile(root)
        if default_profile and os.path.isdir(os.path.join(root, default_profile)):
            return os.path.join(root, default_profile)
        return root

    if browser_name in {"chrome", "chromium", "brave", "edge", "opera", "vivaldi", "whale"}:
        settings = _get_chromium_based_browser_settings(browser_name)
        browser_dir = settings["browser_dir"]
        if not os.path.isdir(browser_dir):
            return None
        # selenium passes this via --user-data-dir, which expects the data root;
        # chrome selects its own last-used profile unless told otherwise
        return browser_dir

    return None


def _firefox_default_profile(root):
    import configparser

    def read_ini(ini_name):
        ini_path = os.path.join(root, ini_name)
        if not os.path.isfile(ini_path):
            return None
        parser = configparser.RawConfigParser()
        try:
            with open(ini_path, encoding="utf8") as f:
                parser.read_file(f)
        except (configparser.Error, OSError):
            return None
        return parser

    installs = read_ini("installs.ini")
    if installs:
        for section in installs.sections():
            if section.lower().startswith("install"):
                default = installs.get(section, "Default", fallback=None)
                if default and os.path.isdir(os.path.join(root, default)):
                    return default

    profiles = read_ini("profiles.ini")
    if not profiles:
        return None
    sections = [s for s in profiles.sections() if s.lower().startswith("profile")]
    for section in sections:
        if profiles.get(section, "Default", fallback="") == "1":
            path = profiles.get(section, "Path", fallback=None)
            if path and os.path.isdir(os.path.join(root, path)):
                return path
    return next((p for p in (profiles.get(s, "Path", fallback=None) for s in sections) if p), None)


def copy_firefox_profile_for_selenium(source_profile, selenium_profile):
    selenium_profile.mkdir(parents=True, exist_ok=True)
    source_cookies = source_profile / "cookies.sqlite"
    if source_cookies.exists():
        for suffix in ("", "-wal", "-shm"):
            src_file = source_cookies.with_suffix(source_cookies.suffix + suffix)
            if src_file.exists():
                shutil.copy2(src_file, selenium_profile / src_file.name)
    for name in ("logins.json", "key4.db", "cert9.db", "permissions.sqlite"):
        src_file = source_profile / name
        if src_file.exists():
            shutil.copy2(src_file, selenium_profile / name)


SKIP_CHROMIUM_DIRS = {"Cache", "Code Cache", "GPUCache", "Service Worker", "Service Worker/CacheStorage", "Session Storage", "Sessions", "databases", "blob_storage", "File System", "IndexedDB", "WebStorage", "GamepadMappings", "safe_browsing", "SafetyTips", "Subresource Filter", "BudgetDatabase", "CELPuzzles", "Crowd Deny", "MEIPreload", "Segmentation Platform", "TranslateRanker", "TranslateScripts", "VideoDecodeStats"}


def copy_chromium_profile_for_selenium(source_profile, selenium_profile):
    source_profile = Path(source_profile)
    selenium_profile = Path(selenium_profile)
    for item in source_profile.iterdir():
        if item.name in SKIP_CHROMIUM_DIRS or item.name in {"LOCK", "LOG", "LOG.old"} or item.name.startswith(".org.chromium."):
            continue
        if item.is_dir():
            shutil.copytree(item, selenium_profile / item.name, ignore=shutil.ignore_patterns("*.lock", "LOCK"))
        else:
            shutil.copy2(item, selenium_profile / item.name)


def load_selenium(args, wire=False):
    if getattr(args, "driver", False):
        return

    _profile = None
    if not args.user_data_dir and getattr(args, "cookies_from_browser", None):
        from library.utils.web import parse_cookies_from_browser

        browser_name, profile, _keyring, _container = parse_cookies_from_browser(args.cookies_from_browser)
        resolved = get_browser_profile_path(browser_name, profile)
        if resolved:
            args.user_data_dir = resolved
            args.profile_directory = profile
            _profile = profile
            log.info("Using browser profile: %s", resolved)
            if browser_name == "firefox" and not getattr(args, "chrome", False):
                args.firefox = True
            elif browser_name in {"chrome", "chromium", "brave", "edge", "opera", "vivaldi", "whale"}:
                args.chrome = True

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

    if (which("firefox") or getattr(args, "firefox", False)) and not getattr(args, "chrome", False):
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service

        service = Service(log_path=tempfile.mktemp(".geckodriver.log"))
        options = Options()

        _using_real_profile = bool(args.user_data_dir)
        if _using_real_profile:
            _real_profile = Path(args.user_data_dir)
            _selenium_profile = Path(tempfile.mkdtemp(prefix="ff_selenium_")) / "profile"
            copy_firefox_profile_for_selenium(_real_profile, _selenium_profile)
            args.selenium_profile_dir = _selenium_profile
            args.user_data_dir = str(_selenium_profile)
            log.info("Selenium profile: %s (cookies from %s)", _selenium_profile, _real_profile)

        if args.user_data_dir:
            options.add_argument("--profile")
            options.add_argument(args.user_data_dir)

        options.set_preference("media.volume_scale", "0.0")
        if xvfb is False:
            options.add_argument("--headless")

        args.driver = webdriver.Firefox(service=service, options=options)

        if not _using_real_profile:
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

        _using_real_profile = bool(args.user_data_dir)
        if _using_real_profile:
            _real_profile = Path(args.user_data_dir)
            _profile_name = _profile or "Default"
            _real_profile_dir = _real_profile / _profile_name
            _selenium_profile = Path(tempfile.mkdtemp(prefix="chrome_selenium_"))
            copy_chromium_profile_for_selenium(_real_profile_dir, _selenium_profile / _profile_name)
            for name in ("Local State",):
                src_file = _real_profile / name
                if src_file.exists():
                    shutil.copy2(src_file, _selenium_profile / name)
            args.selenium_profile_dir = _selenium_profile
            args.user_data_dir = str(_selenium_profile)
            log.info("Selenium profile: %s (cookies from %s)", _selenium_profile, _real_profile_dir)

        if args.user_data_dir:
            options.add_argument(f"--user-data-dir={args.user_data_dir}")
            if _using_real_profile:
                options.add_argument(f"--profile-directory={_profile_name}")
            elif _profile:
                options.add_argument(f"--profile-directory={_profile}")
        else:
            options.add_experimental_option(
                "prefs",
                {
                    "credentials_enable_service": False,
                    "profile.password_manager_enabled": False,
                    "profile.default_content_setting_values.notifications": 2,
                },
            )
        options.add_argument("--disable-notifications")
        options.add_argument("--mute-audio")
        if xvfb is False:
            options.add_argument("--headless=new")

        if not _using_real_profile:
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
    _selenium_dir = getattr(args, "selenium_profile_dir", None)
    if _selenium_dir:
        shutil.rmtree(_selenium_dir, ignore_errors=True)
    if args.verbose < consts.LOG_DEBUG and not getattr(args, "manual", False):
        with suppress(Exception):
            args.driver_display.stop()


def post_download(args):
    sleep_interval = getattr(args, "sleep_interval", None) or 0
    max_sleep_interval = getattr(args, "max_sleep_interval", None)
    if max_sleep_interval:
        sleep_interval = random.uniform(sleep_interval, max_sleep_interval)

    if sleep_interval > 0:
        log.debug("[download] Sleeping %s seconds ...", sleep_interval)
        time.sleep(sleep_interval)


def filename_from_content_disposition(response):
    content_disposition = response.headers.get("Content-Disposition", "")
    if not content_disposition:
        return None

    # Handle filename* (RFC 5987)
    filename_star_match = re.search(r"filename\*=UTF-8\\?'\\?'([^;]+)", content_disposition, re.IGNORECASE)
    if filename_star_match:
        with suppress(Exception):
            return urllib.parse.unquote(filename_star_match.group(1))

    # Handle filename (RFC 2183)
    if "filename=" in content_disposition.lower():
        msg = Message()
        msg["content-disposition"] = content_disposition
        filename = msg.get_filename()
        if filename:
            return filename

    return None


def url_to_local_path(url, response=None, output_prefix=None):
    dir_path, filename = path_tuple_from_url(url)

    if response:
        filename_from_site = filename_from_content_disposition(response)
        if filename_from_site:
            if url.endswith("/"):
                filename = path_utils.safe_join(filename, filename_from_site)
            else:
                filename = filename_from_site

    if not filename:
        content_type = ""
        if response:
            content_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()

        if not content_type or content_type in HTML_MIME_TYPES:
            filename = "index.html"
        elif content_type in XML_MIME_TYPES or content_type.endswith("+xml"):
            filename = "index.xml"

    output_path = filename
    if dir_path:
        output_path = path_utils.safe_join(dir_path, filename)

    output_path = path_utils.clean_path(output_path.encode())

    if output_prefix:
        output_path = path_utils.safe_join(output_prefix, output_path)

    return output_path


def ensure_download_parent(path: Path) -> None:
    parent = path.parent
    while not parent.exists():
        if parent == parent.parent:
            return
        parent = parent.parent

    if parent.is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
        return
    if not parent.is_file():
        raise NotADirectoryError(parent)

    legacy_path = parent.with_name(f"{parent.name}.library-file")
    suffix = 1
    while legacy_path.exists():
        legacy_path = parent.with_name(f"{parent.name}.library-file.{suffix}")
        suffix += 1

    parent.rename(legacy_path)
    parent.mkdir()
    legacy_path.rename(parent / "index.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    log.warning("Moved existing file %s to %s to create a download directory", legacy_path, parent)


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

        code = HTTPStatus(r.status_code)
        if code.is_client_error or code.is_server_error:
            log.error(f"Error {r.status_code} {url}")
            raise_for_status(r.status_code)

        remote_size = nums.safe_int(r.headers.get("Content-Length"))

        if not output_path:
            output_path = url_to_local_path(url, response=r, output_prefix=args.prefix)
        if output_path == ".":
            log.warning("Skipping directory %s", url)
            return None

        p = Path(output_path)
        ensure_download_parent(p)
        if p.exists():
            if p.is_dir():
                log.warning("[%s]: Skipping directory %s", url, p)
                return None

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
                        f"Resuming download. {strings.file_size(local_size)} => {strings.file_size(remote_size)} ({strings.percent(local_size / remote_size)}): {output_path}"
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

            if remote_size and not getattr(args, "ignore_size", False):
                downloaded_size = os.path.getsize(output_path)
                if downloaded_size < remote_size:
                    msg = f"Incomplete download ({strings.percent(downloaded_size / remote_size)}) {output_path}"
                    raise RuntimeError(msg)
        except Exception as excinfo:
            r.close()
            if isinstance(excinfo, HTTPTooManyRequests):
                raise
            if isinstance(excinfo, OSError) and excinfo.errno in consts.EnvironmentErrors:
                raise
            retry_num += 1
            log.debug("Retry #%s %s", retry_num, url)
            time.sleep(retry_num)
            return download_url(args, url, output_path, retry_num)

        set_timestamp(r.headers, output_path)
    except requests.exceptions.SSLError as excinfo:
        if args.allow_insecure and url.startswith("https://"):
            return download_url(args, url.replace("https://", "http://", 1), output_path, retry_num)
        log.error("%s %s", url, excinfo)
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.RetryError,
        urllib3.exceptions.MaxRetryError,
        urllib3.exceptions.NameResolutionError,
        socket.gaierror,
    ) as excinfo:
        log.error("%s %s", url, excinfo)
    finally:
        if "r" in locals():  # prevent UnboundLocalError
            r.close()

    post_download(args)
    if not output_path or not Path(output_path).exists():
        return None
    return output_path


def load_cdx_toolkit():
    global cdx_toolkit

    if cdx_toolkit is None:
        try:
            import cdx_toolkit as _cdx_toolkit
        except ModuleNotFoundError:
            log.error(
                "cdx_toolkit is required for --webcache. Install with pip install cdx_toolkit"
                " or pip install library[deluxe]"
            )
            raise

        cdx_toolkit = _cdx_toolkit
    return cdx_toolkit


def load_internetarchive():
    global internetarchive

    if internetarchive is None:
        import internetarchive as ia

        internetarchive = ia
    return internetarchive


def internet_archive_identifier(url: str) -> str | None:
    parsed_url = urlparse(url)
    if parsed_url.netloc.lower() not in {"archive.org", "www.archive.org"}:
        return None

    path_parts = parsed_url.path.split("/")
    if len(path_parts) < 3 or path_parts[1].lower() != "details" or not path_parts[2]:
        return None

    return urllib.parse.unquote(path_parts[2])


def download_internet_archive(args, url: str) -> str | None:
    identifier = internet_archive_identifier(url)
    if identifier is None:
        raise ValueError(f"Not an Internet Archive details URL: {url}")

    log.info("Downloading Internet Archive item %s", identifier)
    ia = load_internetarchive()
    from internetarchive.exceptions import AccountAPIError, AuthenticationError, InvalidChecksumError, ItemLocateError

    current_file = None
    progress_started = False
    access_restricted = False
    try:
        item = ia.get_item(identifier, archive_session=_get_internet_archive_session(args))
        item_metadata = getattr(item, "item_metadata", {}) or {}
        metadata = item_metadata.get("metadata", {}) or getattr(item, "metadata", {}) or {}
        access_restricted = _is_internet_archive_flag(metadata.get("access-restricted-item"))

        if _is_internet_archive_flag(item_metadata.get("servers_unavailable")):
            msg = f"RecoverableError: Internet Archive item servers unavailable: {identifier}"
            log.warning(msg)
            raise RecoverableError(msg)
        if _is_internet_archive_flag(item_metadata.get("nodownload")):
            msg = f"RecoverableError: Internet Archive item marked nodownload: {identifier}"
            log.warning(msg)
            raise RecoverableError(msg)
        if _is_internet_archive_flag(item_metadata.get("is_dark")):
            msg = f"UnrecoverableError: Internet Archive item is dark: {identifier}"
            log.warning(msg)
            raise UnrecoverableError(msg)

        original_files = []
        private_files = []
        for archive_file in item.get_files():
            if archive_file.source != "original":
                continue
            if archive_file.name in {f"{identifier}_files.xml", "__ia_thumb.jpg"}:
                log.info("Skipping Internet Archive generated file %s", archive_file.name)
                continue
            if str(getattr(archive_file, "private", "")).lower() == "true":
                private_files.append(archive_file)
                log.info("Skipping private Internet Archive file %s", archive_file.name)
                continue
            original_files.append(archive_file)

        if not original_files:
            if private_files:
                log.info("Internet Archive item %s has no downloadable public original files", identifier)
                return str(Path(args.prefix).expanduser() / identifier)
            raise RuntimeError(f"Internet Archive item has no downloadable original files: {identifier}")

        destdir = str(Path(args.prefix).expanduser())
        archive_root = Path(destdir).expanduser().resolve() / identifier
        errors = []
        for index, archive_file in enumerate(original_files, start=1):
            current_file = archive_file.name
            progress_started = True
            local_path = archive_root / archive_file.name
            if not local_path.resolve().is_relative_to(archive_root):
                raise RuntimeError(f"Unsafe Internet Archive file path: {archive_file.name}")

            remote_size = nums.safe_int(getattr(archive_file, "size", None))
            if local_path.is_file() and remote_size is not None and local_path.stat().st_size == remote_size:
                message = (
                    f"Skipping Internet Archive item {identifier} ({index}/{len(original_files)}): "
                    f"{archive_file.name} (same size)"
                )
                printing.print_overwrite(message)
                continue

            message = f"Downloading Internet Archive item {identifier} ({index}/{len(original_files)}): {archive_file.name}"
            printing.print_overwrite(message)
            file_errors = item.download(
                files=[archive_file.name],
                source="original",
                checksum=True,
                destdir=destdir,
                # The IA client treats 0, False, and None as its default retry count.
                retries=INTERNET_ARCHIVE_NO_RETRIES,
            )
            errors.extend(file_errors)
    except (
        AccountAPIError,
        AuthenticationError,
        InvalidChecksumError,
        ItemLocateError,
        OSError,
        requests.exceptions.RequestException,
    ) as excinfo:
        target = f"{identifier}/{current_file}" if current_file else identifier
        access_message = " (access-restricted-item=true; item may require a loan)" if access_restricted else ""
        raise RuntimeError(f"Internet Archive download failed for {target}{access_message}: {excinfo}") from excinfo
    finally:
        if progress_started:
            print(file=sys.stderr)

    if errors:
        access_message = " (access-restricted-item=true; item may require a loan)" if access_restricted else ""
        raise RuntimeError(
            f"Internet Archive files failed to download for {identifier}{access_message}: {', '.join(errors)}"
        )

    return str(Path(args.prefix).expanduser() / identifier)


def download_link(args, url: str) -> str | None:
    if internet_archive_identifier(url) is not None:
        return download_internet_archive(args, url)
    return download_url(args, url)


def get_elements_forward(start, end):
    elements = []
    current_tag = start.next_sibling
    while current_tag and current_tag != end:
        if isinstance(current_tag, element.NavigableString):  # type: ignore
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
                if isinstance(current_tag, element.NavigableString):
                    text = strings.un_paragraph(current_tag.get_text()).strip()
                    if text and text not in before_text:
                        before_text.append(text)
                current_tag = current_tag.previous_element
            before_text.reverse()

        current_tag = tag.next_sibling
        while current_tag and (i == len(tags) - 1 or current_tag != tags[i + 1]):  # end tag or until next tag
            if isinstance(current_tag, element.NavigableString):
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
    global cookie_jar
    load_cookie_jar(args)

    using_native_profile = bool(getattr(args, "user_data_dir", None))

    if cookie_jar and not using_native_profile:
        if path_utils.fqdn_from_url(url) != path_utils.fqdn_from_url(args.driver.current_url):
            args.driver.get(path_utils.fqdn_from_url(url))

        for cookie in cookie_jar.get_cookies_for_url(url):
            cookie_dict = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "secure": bool(cookie.secure),
            }
            if cookie.expires:
                cookie_dict["expiry"] = cookie.expires
            if cookie.path_specified:
                cookie_dict["path"] = cookie.path
            with suppress(Exception):
                args.driver.add_cookie(cookie_dict)

    args.driver.get(url)
    args.driver.implicitly_wait(5)

    if getattr(args, "poke", False):
        re_trigger_input(args.driver)

    if cookie_jar:
        new_cookies = args.driver.get_cookies()

        for new_cookie in new_cookies:
            new_cookie = http.cookiejar.Cookie(
                version=0,
                name=new_cookie["name"],
                value=new_cookie["value"],
                port=None,
                port_specified=False,
                domain=new_cookie["domain"],
                domain_specified=bool(new_cookie["domain"]),
                domain_initial_dot=new_cookie["domain"].startswith("."),
                path=new_cookie["path"],
                path_specified=bool(new_cookie["path"]),
                secure=new_cookie["secure"],
                expires=new_cookie.get("expiry"),
                discard=False,
                comment=None,
                comment_url=None,
                rest={},
            )
            cookie_jar.set_cookie(new_cookie)


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
        """
            (function(){
            function k(x) {
                if (typeof x.onmouseover === "function") {
                x.onmouseover();
                x.backupmouseover = x.onmouseover;
                x.backupmouseout = x.onmouseout;
                x.onmouseover = null;
                x.onmouseout = null;
                } else if (typeof x.backupmouseover === "function") {
                x.onmouseover = x.backupmouseover;
                x.onmouseout = x.backupmouseout;
                if (typeof x.onmouseover === "function") x.onmouseover();
                if (typeof x.onmouseout === "function") x.onmouseout();
                }
            }

            var i, x;
            for (i = 0; (x = document.links[i]); ++i) k(x);
            for (i = 0; (x = document.images[i]); ++i) k(x);
        })();
        """
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

    if href.startswith("//"):
        return "https:" + href

    if not up.netloc:
        href = urljoin(base_url, href)

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


WAYBACK_URL_RE = re.compile(
    r"^https?://web\.archive\.org/web/(?P<timestamp>\d{4,14})(?P<modifier>[a-z_]*)"
    r"/(?P<original>.+)$",
    re.IGNORECASE,
)


def is_wayback_url(url: str) -> bool:
    return WAYBACK_URL_RE.match(url) is not None


def wayback_timestamp(url: str) -> str | None:
    match = WAYBACK_URL_RE.match(url)
    return match.group("timestamp") if match else None


def wayback_original_url(url: str) -> str | None:
    """Return the archived URL from a Wayback Machine URL, or None if not a Wayback URL."""
    match = WAYBACK_URL_RE.match(url)
    if not match:
        return None

    original = match.group("original")
    # treat http:/ and http:// Wayback URLs as equivalent
    original = original.replace("http:///", "http://").replace("https:///", "https://")
    if not original.startswith(("http://", "https://")):
        original = original.replace("http:/", "http://", 1).replace("https:/", "https://", 1)
    return original


def wayback_normalize(url: str) -> str:
    """Collapse a Wayback Machine URL to its original archived URL (for scope and dedup)."""
    return wayback_original_url(url) or url


def wayback_snapshot_url(timestamp: str, original: str) -> str:
    """Build a directly-downloadable Wayback Machine snapshot URL."""
    return f"https://web.archive.org/web/{timestamp}id_/{original}"


def wayback_replay_url(url: str) -> str:
    """Return the Wayback replay URL (modifier stripped) so served HTML links stay within the archive."""
    match = WAYBACK_URL_RE.match(url)
    if not match:
        return url
    return f"https://web.archive.org/web/{match.group('timestamp')}/{match.group('original')}"


def is_subpath(parent_url, child_url):
    parent = urlparse(urldefrag(parent_url)[0])
    child = urlparse(urldefrag(child_url)[0])

    if child.scheme != parent.scheme or child.netloc != parent.netloc:
        return False
    elif not child.path:
        return False

    parent_parts = parent.path.split("/")
    if not parent.path.endswith("/"):
        parent_parts.pop()

    parent_path = "/".join(parent_parts)
    return child.path.startswith(parent_path)


media_extensions = tuple(
    "." + ext
    for ext in consts.IMAGE_EXTENSIONS
    | consts.ARCHIVE_EXTENSIONS
    | consts.IMAGE_ANIMATION_EXTENSIONS
    | consts.PIL_EXTENSIONS
    | consts.VIDEO_EXTENSIONS
    | consts.AUDIO_ONLY_EXTENSIONS
    | consts.OCRMYPDF_EXTENSIONS
    | consts.HTML_SIDECAR_EXTENSIONS
)


def is_html(args, url, max_size=2 * 1024 * 1024):
    if url.endswith(media_extensions):
        return False

    r = None
    try:
        r = requests_session().head(url, timeout=(5, 8))

        content_length = r.headers.get("Content-Length")
        if content_length and int(content_length) > max_size:
            return False

        content_type = r.headers.get("Content-Type")
        if content_type and not any(s in content_type for s in HTML_MIME_TYPES + XML_MIME_TYPES):
            # log.debug('not is_html %s %s', content_type, url)
            return False
    except requests.exceptions.RetryError:
        return False
    finally:
        if r:
            r.close()

    sleep(args)

    return True  # if ambiguous, return True


def fake_title(url):
    p = urllib.parse.urlparse(url)
    title = f"{p.netloc} {p.path} {p.params} {p.query}: {p.fragment}"

    title = title.removeprefix("www.")

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
            html_text = Path(url).read_text()
            url = "file://" + url
        elif args.selenium:
            selenium_get_page(args, url)
            html_text = args.driver.page_source
        else:
            html_text = session.get(url).text

        soup = BeautifulSoup(html_text, "lxml")
        title = soup.title.text.strip() if soup.title else url
    except requests.exceptions.RequestException:
        title = fake_title(url)

    sleep(args)

    if title.startswith("Stream ") and "SoundCloud" in title:
        title = title.replace("Stream ", "", 1)

    for x in consts.COMMON_SITE_TITLE_SUFFIXES:
        title = title.replace(x, "")

    title = strings.remove_consecutive_whitespace(title)

    log.info("[%s]: got title %s", url, title)
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
        self._head = None

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
            parts += [p for p in res.path.split("/") if p]
        if res.params:
            parts += [p for p in res.params.split("&") if p]
        if res.query:
            parts += [p for p in res.query.split("&") if p]
        if res.fragment:
            parts += [p for p in res.fragment.split("&") if p]
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

        code = HTTPStatus(r.status_code)
        if code.is_informational or code.is_success or code.is_redirection:
            return WebStatResult(r)
        elif r.status_code == HTTPStatus.NOT_FOUND:
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

    def unlink(self, *args, **kwargs):
        pass

    def as_posix(self) -> str:
        return path_utils.safe_join(*path_tuple_from_url(str(self)))

    def remote_name(self):
        return filename_from_content_disposition(self.head())

    def __truediv__(self, other):
        return WebPath(f"{self!s}/{other!s}")

    def __str__(self):
        return self._path


@processes.with_timeout_thread(max(consts.REQUESTS_TIMEOUT) + 5)
def stat(url, follow_symlinks=True):
    global session
    if session is None:
        log.warning("Creating new web.session")
        session = requests_session()

    r = session.head(url, allow_redirects=follow_symlinks)

    code = HTTPStatus(r.status_code)
    if code.is_informational or code.is_success or code.is_redirection:
        return WebStatResult(r)
    elif r.status_code == HTTPStatus.NOT_FOUND:
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
