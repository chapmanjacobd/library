import tempfile
from pathlib import Path
from typing import List, Optional, Union

import ffmpeg, pysubs2, sqlite_utils
from ffmpeg import Error

from xklb.consts import SUB_TEMP_DIR
from xklb.utils import cmd, flatten, log, remove_text_inside_brackets, remove_whitespaace, replace_consecutive

SUBTITLE_FORMATS = "vtt|srt|ssa|ass|jss|aqt|mpl2|mpsub|pjs|rt|sami|smi|stl|xml|txt|psb|ssf|usf"
IMAGE_SUBTITLE_CODECS = ["dvbsub", "dvdsub", "pgssub", "xsub", "dvb_subtitle", "dvd_subtitle", "hdmv_pgs_subtitle"]


def extract(video_file, stream_index) -> Optional[str]:
    temp_srt = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)

    stream_id = "0:" + str(stream_index)

    try:
        ffmpeg.input(video_file).output(temp_srt, map=stream_id).global_args("-nostdin").run(quiet=True)
    except Error as e:
        log.info(
            f"Could not extract subtitle {stream_id} from video file. Likely incorrect subtitle character encoding set. %s",
            video_file,
        )
        log.debug(e.stderr.decode())
        return None

    return temp_srt


def convert_to_srt(path) -> str:
    temp_srt = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)
    try:
        ffmpeg.input(path).output(temp_srt).global_args("-nostdin").run(quiet=True)
    except Error as e:
        log.info("Could not convert subtitle")
        log.info(e.stderr.decode())
        raise UnicodeDecodeError("utf-8", b"Dr. John A. Zoidberg", 1, 2, "Bleh!")

    return temp_srt


def read_sub_unsafe(path) -> List[str]:
    return [
        remove_text_inside_brackets(caption.text.replace(r"\N", " ").replace(r"\n", " ").replace("\n", " "))
        for caption in pysubs2.load(path, format_="srt")
    ]


def read_sub(path) -> List[str]:
    if Path(path).suffix.lower() != ".srt":
        path = convert_to_srt(path)

    try:
        return read_sub_unsafe(path)
    except UnicodeDecodeError:
        return read_sub_unsafe(convert_to_srt(path))


def subs_to_text(video_path, paths: List[str]) -> str:
    def sub_to_text(path):
        try:
            return read_sub(path)
        except UnicodeDecodeError:
            log.warning(f"[{video_path}] Could not decode subtitle {path}")
            return []

    subtitles = " ".join(list(dict.fromkeys(flatten([sub_to_text(path) for path in paths]))))
    return remove_whitespaace(subtitles)


def externalize_subtitle(media_file) -> Union[str, None]:
    subs = ffmpeg.probe(media_file)["streams"]

    subtitles_file = None
    if subs:
        db = sqlite_utils.Database(memory=True)
        db["subs"].insert_all(subs, pk="index")  # type: ignore
        subtitle_index = db.execute_returning_dicts(
            """select "index" from subs
                order by
                    lower(tags) like "%eng%" desc
                    , lower(tags) like "%dialog%" desc
                limit 1"""
        )[0]["index"]
        log.debug(f"Using subtitle {subtitle_index}")

        subtitles_file = cmd("mktemp", "--suffix=.vtt", "--dry-run").stdout.strip()
        cmd(
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "warning",
            "-txt_format",
            "text",
            "-i",
            media_file,
            "-map",
            f"0:{subtitle_index}",
            subtitles_file,
            strict=False,
        )

        if Path(subtitles_file).exists():
            return subtitles_file


def get_external(file) -> List[str]:
    p = Path(file)

    subtitles = [
        str(sub_p) for sub_p in p.parent.glob(p.stem + "*") if sub_p.suffix[1:].lower() in SUBTITLE_FORMATS.split("|")
    ]

    if subtitles:
        return subtitles

    return []
