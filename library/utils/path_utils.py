import os.path
from collections import Counter, OrderedDict
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlunparse

from idna import decode as puny_decode

from library.utils import consts, iterables, strings


def random_filename(path) -> str:
    ext = Path(path).suffix
    path = str(Path(path).with_suffix(""))
    return f"{path}.{consts.random_string()}{ext}"


def trim_path_segments(path, desired_length):
    path = Path(path)
    segments = [*list(path.parent.parts), path.stem]
    extension = path.suffix

    desired_length -= len(extension)

    while len("".join(segments)) > desired_length:
        longest_segment_index = max(range(len(segments)), key=lambda i: len(segments[i]))
        segments[longest_segment_index] = segments[longest_segment_index][:-1]

        if all(len(segment) % 2 == 0 for segment in segments):
            for i in range(len(segments)):
                segments[i] = segments[i][:-1]

    segments[-1] += extension
    return str(Path(*segments))


def clean_path(b, max_name_len=255, dot_space=False, case_insensitive=False, lowercase_folders=False) -> str:
    import ftfy

    p = b.decode("utf-8", "backslashreplace")
    p = ftfy.fix_text(p, explain=False)
    path = Path(p)
    ext = path.suffix

    pre = ""
    if path.drive and path.drive.endswith(":"):
        pre = path.drive
        path = Path(str(path)[len(path.drive) :])

    parent = [strings.clean_string(part) for part in path.parent.parts]
    stem = strings.clean_string(path.stem)
    # log.debug("cleaned %s %s", parent, stem)

    parent = [strings.remove_prefixes(part, [" ", "-"]) for part in parent]
    # log.debug("parent_prefixes %s %s", parent, stem)
    parent = [strings.remove_suffixes(part, [" ", "-", "_", "."]) for part in parent]
    # log.debug("parent_suffixes %s %s", parent, stem)

    stem = strings.remove_prefixes(stem, [" ", "-"])
    stem = strings.remove_suffixes(stem, [" ", "-", "."])
    # log.debug("stem %s %s", parent, stem)

    parent = ["_" if part == "" else part for part in parent]
    if lowercase_folders:
        parent = [p.lower() for p in parent]
    elif case_insensitive:

        def case_insensitive_r(p):
            if any(x in p[1:-1] for x in (" ", "_", ".")):
                return p.title()
            else:
                return p.lower()

        parent = [case_insensitive_r(p) for p in parent]

    fs_limit = max_name_len - len(ext.encode()) - len("...") - 1
    if len(stem.encode()) > fs_limit:
        start = stem[: fs_limit // 2]
        end = stem[-fs_limit // 2 :]
        while len(start.encode()) > fs_limit // 2:
            start = start[:-1]
        while len(end.encode()) > fs_limit // 2:
            end = end[1:]
        stem = start + "..." + end

    p = str(Path(*parent) / stem)

    if dot_space:
        p = p.replace(" ", ".")

    return pre + p + ext


def sanitize_url(args, path: str) -> str:
    matches = consts.REGEX_SUBREDDIT.match(path)
    if matches:
        subreddit = iterables.conform(matches.groups())[0]
        frequency = "monthly"
        if hasattr(args, "frequency"):
            frequency = args.frequency
        return "https://old.reddit.com/r/" + subreddit + "/top/?sort=top&t=" + consts.reddit_frequency(frequency)

    if "/m." in path:
        return path.replace("/m.", "/www.")

    return path


def dedupe_path_parts(p):
    return Path(*OrderedDict.fromkeys(Path(p).parts).keys())


def common_path_full(paths):
    common_prefix = os.path.commonprefix(paths)

    suffix_words = []
    for path in paths:
        suffix = path[len(common_prefix) :]
        words = list(iterables.ordered_set(strings.path_to_sentence(suffix).split()))
        suffix_words.extend(words)

    word_counts = Counter(suffix_words)
    common_words = [w for w, c in word_counts.items() if c > int(len(paths) * 0.6) and len(w) > 1]

    # join but preserve order
    suffix = "*".join(s for s in iterables.ordered_set(suffix_words) if s in common_words)

    common_path = common_prefix.strip() + "*" + suffix
    return common_path


def bfs_removedirs(root_dir):
    for dirpath, _, _ in os.walk(root_dir, topdown=False):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass


def ext(path):
    return str(path).rsplit(".", 1)[-1].lower()


def parent(s):
    return os.path.basename(os.path.dirname(s))


def basename(path):
    """A basename() variant which first strips the trailing slash, if present.
    Thus we always get the last component of the path, even for directories.

    e.g.
    >>> os.path.basename('/bar/foo')
    'foo'
    >>> os.path.basename('/bar/foo/')
    ''
    """
    path = os.fspath(path)
    sep = os.path.sep + (os.path.altsep or "")
    return os.path.basename(path.rstrip(sep))


def build_nested_dir_dict(path_str, nested_value):
    p = Path(path_str)
    if p.drive.endswith(":"):  # Windows Drives
        drive = p.drive.strip(":")
        segments = (drive, *p.parts[1:])
    elif p.drive.startswith("\\\\"):  # UNC paths
        server_share = p.parts[0]
        segments = (*server_share.lstrip("\\").split("\\"), *p.parts[1:])
    else:
        segments = p.parts[1:]

    def _build_dict(segments):
        if not segments:
            return nested_value
        return {segments[0]: _build_dict(segments[1:])}

    return _build_dict(segments)


def is_empty_folder(path):
    folder = Path(path)

    if not any(folder.iterdir()):
        return True

    for file_path in folder.rglob("*"):
        if file_path.is_file() and file_path.stat().st_size != 0:
            return False

    return True


def folder_size(path):
    folder = Path(path)

    size = 0
    for file_path in folder.rglob("*"):
        if file_path.is_file():
            size += file_path.stat().st_size

    return size


def folder_utime(folder_path, times: tuple[int, int] | tuple[float, float]):
    folder = Path(folder_path)

    os.utime(folder, times)

    for file_path in folder.rglob("*"):
        if file_path.is_file():
            os.utime(file_path, times)


def domain_from_url(tracker):
    url = urlparse(tracker)
    domain = ".".join(url.netloc.rsplit(":")[0].rsplit(".", 2)[-2:]).lower()
    return domain


def mountpoint(path):
    path = os.path.abspath(path)

    path_dev = os.stat(path).st_dev
    while path != os.path.dirname(path):
        parent = os.path.dirname(path)  # go up

        if os.stat(parent).st_dev != path_dev:
            return path
        path = parent

    raise RuntimeError("Could not find drive / mountpoint")


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
    filename = basename(parsed_url.path)
    return parent_path, filename