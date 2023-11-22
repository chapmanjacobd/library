from pathlib import Path

from xklb.utils import consts, iterables, strings
from xklb.utils.log_utils import log


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


def clean_path(b, max_name_len=1024, dot_space=False, case_insensitive=False, lowercase_folders=False) -> str:
    import ftfy

    p = b.decode("utf-8", "backslashreplace")
    p = ftfy.fix_text(p, explain=False)
    path = Path(p)
    ext = path.suffix

    parent = [strings.clean_string(part) for part in path.parent.parts]
    stem = strings.clean_string(path.stem)
    log.debug("cleaned %s %s", parent, stem)

    parent = [strings.remove_prefixes(part, [" ", "-"]) for part in parent]
    log.debug("parent_prefixes %s %s", parent, stem)
    parent = [strings.remove_suffixes(part, [" ", "-", "_", "."]) for part in parent]
    log.debug("parent_suffixes %s %s", parent, stem)

    stem = strings.remove_prefixes(stem, [" ", "-"])
    stem = strings.remove_suffixes(stem, [" ", "-", "."])
    log.debug("stem %s %s", parent, stem)

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

    ffmpeg_limit = max_name_len - len(ext.encode()) - len("...")
    if len(stem.encode()) > ffmpeg_limit:
        start = stem[: ffmpeg_limit // 2]
        end = stem[-ffmpeg_limit // 2 :]
        while len(start.encode()) > ffmpeg_limit // 2:
            start = start[:-1]
        while len(end.encode()) > ffmpeg_limit // 2:
            end = end[1:]
        stem = start + "..." + end

    p = str(Path(*parent) / stem)

    if dot_space:
        p = p.replace(" ", ".")

    return p + ext


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
