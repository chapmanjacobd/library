import functools, os, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from shutil import which

from xklb.utils import nums, path_utils
from xklb.utils.log_utils import log

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


def load_selenium(args):
    from selenium import webdriver

    if which("firefox"):
        args.driver = webdriver.Firefox()
    else:
        args.driver = webdriver.Chrome()


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
