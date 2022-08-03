import argparse
import logging
import os
import re
import sys
from collections.abc import Iterable
from functools import wraps
from pathlib import Path
from subprocess import run

# import ipdb
from IPython.core import ultratb
from IPython.terminal.debugger import TerminalPdb
from pychromecast import discovery
from rich import inspect, print
from rich.logging import RichHandler

# sys.breakpointhook = ipdb.set_trace


def parse_args(default_chromecast):
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs='?', default='videos.db')

    # TODO: maybe try https://dba.stackexchange.com/questions/43415/algorithm-for-finding-the-longest-prefix
    parser.add_argument("-O", "--play-in-order", action="count", default=0)
    parser.add_argument("-S", "--skip")
    parser.add_argument("-u", "--sort")
    parser.add_argument("-w", "--where")
    parser.add_argument("--only-video", action="store_true")

    parser.add_argument("-d", "--duration", type=int)
    parser.add_argument("-dM", "--max-duration", type=int)
    parser.add_argument("-dm", "--min-duration", type=int)

    parser.add_argument("-s", "--search")
    parser.add_argument("-E", "--exclude")

    parser.add_argument("-cast-to", "--chromecast-device", default=default_chromecast)
    parser.add_argument("-cast", "--chromecast", action="store_true")
    parser.add_argument("-wl", "--with-local", action="store_true")

    parser.add_argument("-f", "--prefix", default="", help="sshfs root prefix")

    parser.add_argument("-z", "--size", type=int)
    parser.add_argument("--max-size", type=int)
    parser.add_argument("--min-size", type=int)

    parser.add_argument("-p", "--print", default=False, const='p', nargs='?')
    parser.add_argument("-L", "--limit", type=int)

    parser.add_argument("-t", "--time-limit", type=int)
    parser.add_argument("-vlc", "--vlc", action="store_true")
    parser.add_argument("--force-transcode", action="store_true")

    parser.add_argument("-k", "--action", default='keep')
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--delete", action="store_true")

    parser.add_argument("-mv", "--move")

    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("-V", "--version")
    args = parser.parse_args()

    if args.version:
        from xklb import __version__

        print(__version__)
        stop()

    if args.keep:
        args.action = 'keep'
    if args.delete:
        args.action = 'delete'

    if args.limit is None:
        args.limit = 1
        if args.print:
            args.limit = 100
            if 'a' in args.print:
                args.limit = 9999999999999

    YEAR_MONTH = lambda var: f"cast(strftime('%Y%m',datetime({var} / 1000000000, 'unixepoch')) as int)"
    if args.sort:
        args.sort = args.sort.replace("time_created", YEAR_MONTH("time_created"))
        args.sort = args.sort.replace("time_modified", YEAR_MONTH("time_modified"))
        args.sort = args.sort.replace("random", "random()")
        args.sort = args.sort.replace("priority", "round(duration / size,7)")
        args.sort = args.sort.replace("sub", "has_sub")

    if args.where:
        args.where = args.where.replace("sub", "has_sub")

    return args


def remove_media(con, filename):
    con.execute("delete from media where filename = ?", (str(filename),))
    con.commit()


def stop():
    exit(255)  # use nonzero code to stop shell repeat


def get_video_files(path, audio=False):
    FFMPEG_DEMUXERS = "str|aa|aac|aax|ac3|acm|adf|adp|dtk|ads|ss2|adx|aea|afc|aix|al|ape|apl|mac|aptx|aptxhd|aqt|ast|obu|avi|avr|avs|avs2|avs3|bfstm|bcstm|binka|bit|bmv|brstm|cdg|cdxl|xl|c2|302|daud|str|adp|dav|dss|dts|dtshd|dv|dif|cdata|eac3|paf|fap|flm|flac|flv|fsb|fwse|g722|722|tco|rco|g723_1|g729|genh|gsm|h261|h26l|h264|264|avc|hca|hevc|h265|265|idf|ifv|cgi|ipu|sf|ircam|ivr|kux|669|abc|amf|ams|dbm|dmf|dsm|far|it|mdl|med|mid|mod|mt2|mtm|okt|psm|ptm|s3m|stm|ult|umx|xm|itgz|itr|itz|mdgz|mdr|mdz|s3gz|s3r|s3z|xmgz|xmr|xmz|669|amf|ams|dbm|digi|dmf|dsm|dtm|far|gdm|ice|imf|it|j2b|m15|mdl|med|mmcmp|mms|mo3|mod|mptm|mt2|mtm|nst|okt|plm|ppm|psm|pt36|ptm|s3m|sfx|sfx2|st26|stk|stm|stp|ult|umx|wow|xm|xpk|flv|dat|lvf|m4v|mkv|mk3d|mka|mks|webm|mca|mcc|mjpg|mjpeg|mpo|j2k|mlp|mods|moflex|mov|mp4|m4a|3gp|3g2|mj2|psp|m4b|ism|ismv|isma|f4v|mp2|m2a|mpa|mpc|mjpg|mpl2|msf|mtaf|ul|musx|mvi|mxg|v|nist|sph|nsp|nut|obu|ogg|oma|omg|aa3|pjs|pvf|yuv|cif|qcif|rgb|rt|rsd|rsd|rso|sw|sb|sami|sbc|msbc|sbg|scc|sdr2|sds|sdx|ser|sga|shn|vb|son|imx|sln|mjpg|stl|sup|svag|svs|tak|thd|tta|ans|art|asc|diz|ice|vt|ty|ty+|uw|ub|v210|yuv10|vag|vc1|rcv|viv|vpk|vqf|vql|vqe|wsd|xmv|xvag|yop|y4m"
    if audio:
        FFMPEG_DEMUXERS += "|opus|oga|mp3"

    video_files = []

    for f in Path(path).resolve().rglob("*"):
        if f.is_file() and (f.suffix.lower()[1:] in FFMPEG_DEMUXERS.split("|")):
            video_files.append(str(f))

    return video_files


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def run_once(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not f.has_run:
            result = f(*args, **kwargs)
            f.has_run = True
            return result

    f.has_run = False
    return wrapper


@run_once
def argparse_log():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args, _unknown = parser.parse_known_args()
    # print(args)

    try:
        if args.verbose > 0 and os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno()):
            sys.excepthook = ultratb.FormattedTB(
                mode="Context",
                color_scheme="Neutral",
                call_pdb=1,
                debugger_cls=TerminalPdb,
            )
        else:
            pass
    except:
        pass

    log_levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    logging.root.handlers = []  # clear any existing handlers
    logging.basicConfig(
        level=log_levels[min(len(log_levels) - 1, args.verbose)],
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler()],
    )
    return logging.getLogger()


log = argparse_log()


def cmd(*command, strict=True, cwd=None, quiet=False):
    EXP_FILTER = re.compile(
        "|".join(
            [
                r".*Stream #0:0.*Audio: opus, 48000 Hz, .*, fltp",
                r".*Metadata:",
            ]
        ),
        re.IGNORECASE,
    )

    def filter_output(string):
        filtered_strings = []
        for s in string.strip().splitlines():
            if not EXP_FILTER.match(s):
                filtered_strings.append(s)

        return "\n".join(list(filter(None, filtered_strings)))

    def print_std(r_std):
        s = filter_output(r_std)
        if not quiet and len(s) > 0:
            print(s)
        return s

    r = run(*command, capture_output=True, text=True, shell=True, cwd=cwd, preexec_fn=os.setpgrp)
    # TODO Windows support: creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    log.debug(r.args)
    r.stdout = print_std(r.stdout)
    r.stderr = print_std(r.stderr)
    if r.returncode != 0:
        log.info(f"ERROR {r.returncode}")
        if strict:
            raise Exception(f"[{command}] exited {r.returncode}")

    return r


def conditional_filter(args):
    B_TO_MB = 1024 * 1024
    size_mb = 0
    if args.size:
        size_mb = args.size * B_TO_MB

    SEC_TO_M = 60
    duration_m = 0
    if args.duration:
        duration_m = args.duration * SEC_TO_M

    cf = f"""duration IS NOT NULL and size IS NOT NULL
    {f'and duration >= {args.min_duration * SEC_TO_M}' if args.min_duration else ''}
    {f'and {args.max_duration * SEC_TO_M} >= duration' if args.max_duration else ''}
    {f'and {duration_m + (duration_m /10)} >= duration and duration >= {duration_m - (duration_m /10)}' if args.duration else ''}
    {f'and size >= {args.min_size * B_TO_MB}' if args.min_size else ''}
    {f'and {args.max_size * B_TO_MB} >= size' if args.max_size else ''}
    {f'and {size_mb + (size_mb /10)} >= size and size >= {size_mb - (size_mb /10)}' if args.size else ''}
    """

    if args.where:
        cf += " and " + args.where

    return " ".join(cf.splitlines())


def compile_query(query, *args):
    if len(args) == 1 and (not args[0]):
        number_of_arguments = 0

    number_of_question_marks = query.count("?")
    number_of_arguments = len(args)
    if number_of_arguments != number_of_question_marks:
        return f"Number of bindings mismatched. The query uses {number_of_question_marks}, but {number_of_arguments} binded parameters."

    for a in args:
        query = query.replace("?", "'" + str(a) + "'", 1)

    return query


def print_query(bindings, query):
    print(re.sub(r"\n\s+", r"\n", compile_query(query, *bindings)))


def single_column_tolist(array_of_half_tuplets, column_name=1):
    return list(
        map(
            lambda x: x[column_name],
            array_of_half_tuplets,
        )
    )


def get_ordinal_media(con, args, filename: Path, sql_filter):
    similar_videos = []
    testname = str(filename)

    total_media = con.execute("select count(*) val from media").fetchone()[0]
    while len(similar_videos) < 2:
        remove_groups = re.split(r"([\W]+|\s+|Ep\d+|x\d+|\.\d+)", testname)
        log.debug(remove_groups)
        remove_chars = ""
        remove_chars_i = 1
        while len(remove_chars) < 1:
            remove_chars += remove_groups[-remove_chars_i]
            remove_chars_i += 1

        newtestname = testname[: -len(remove_chars)]
        log.debug(f"Matches for '{newtestname}':")

        if testname in ["" or newtestname]:
            return filename

        testname = newtestname
        query = f"""SELECT filename FROM media
            WHERE filename like ?
                and {'1=1' if (args.play_in_order > 2) else sql_filter}
            ORDER BY filename
            LIMIT 1000
            """
        bindings = ("%" + testname + "%",)
        if args.print and 'q' in args.print:
            print_query(bindings, query)
            stop()

        similar_videos = single_column_tolist(con.execute(query, bindings).fetchall(), "filename")  # type: ignore
        log.debug(similar_videos)

        if len(similar_videos) > 999 or len(similar_videos) == total_media:
            return filename

        commonprefix = os.path.commonprefix(similar_videos)
        log.debug(commonprefix)
        if len(Path(commonprefix).name) < 3:
            log.debug("Using commonprefix")
            return filename

    return similar_videos[0]


def get_ip_of_chromecast(device_name):
    cast_infos, browser = discovery.discover_listed_chromecasts(friendly_names=[device_name])
    browser.stop_discovery()
    if len(cast_infos) == 0:
        print("Target chromecast device not found")
        exit(53)

    return cast_infos[0].host


def flatten(xs):
    for x in xs:
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        elif isinstance(x, bytes):
            yield x.decode("utf-8")
        else:
            yield x


def remove_None(kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


_RE_COMBINE_WHITESPACE = re.compile(r"\s+")


def conform(list_):
    if not isinstance(list_, list):
        list_ = [list_]
    list_ = flatten(list_)
    list_ = list(filter(None, list_))
    return list_


def combine(*list_):
    list_ = conform(list_)
    if len(list_) == 0:
        return None

    no_comma = sum([s.split(",") for s in list_], [])
    no_semicol = sum([s.split(";") for s in no_comma], [])
    no_double_space = [_RE_COMBINE_WHITESPACE.sub(" ", s).strip() for s in no_semicol]
    no_unknown = [x for x in no_double_space if x.lower() not in ["unknown", "none", "und", ""]]

    no_duplicates = list(set(no_unknown))
    return ";".join(no_duplicates)


def safe_unpack(*list_, idx=0):
    list_ = conform(list_)
    if len(list_) == 0:
        return None

    try:
        return list_[idx]
    except IndexError:
        return None
