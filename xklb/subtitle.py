import tempfile
from pathlib import Path
from typing import List, Optional

import ffmpeg
from ffmpeg import Error

from xklb import db, utils
from xklb.consts import SUB_TEMP_DIR
from xklb.utils import flatten, log, remove_consecutive_whitespace, remove_text_inside_brackets

SUBTITLE_FORMATS = "vtt|srt|ssa|ass|jss|aqt|mpl2|mpsub|pjs|rt|sami|smi|stl|xml|txt|psb|ssf|usf"
IMAGE_SUBTITLE_CODECS = ["dvbsub", "dvdsub", "pgssub", "xsub", "dvb_subtitle", "dvd_subtitle", "hdmv_pgs_subtitle"]


def extract(video_file, stream_index) -> Optional[str]:
    import ffmpeg

    Path(SUB_TEMP_DIR).mkdir(parents=True, exist_ok=True)
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
    import ffmpeg

    Path(SUB_TEMP_DIR).mkdir(parents=True, exist_ok=True)
    temp_srt = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)
    try:
        ffmpeg.input(path).output(temp_srt).global_args("-nostdin").run(quiet=True)
    except Error as e:
        log.info("Could not convert subtitle")
        log.info(e.stderr.decode())
        raise UnicodeDecodeError("utf-8", b"Dr. John A. Zoidberg", 1, 2, "Bleh!") from e

    return temp_srt


def read_sub_unsafe(path) -> List[str]:
    import pysubs2

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
    return remove_consecutive_whitespace(subtitles)


def is_text_subtitle_stream(s) -> bool:
    return s.get("codec_type") == "subtitle" and s.get("codec_name") not in IMAGE_SUBTITLE_CODECS


def externalize_internal_subtitles(f, streams=None) -> List[str]:
    if streams is None:
        streams = ffmpeg.probe(f, show_chapters=None)["streams"]

    external_paths = utils.conform(
        [extract(f, s["index"]) for s in streams if is_text_subtitle_stream(s)],
    )

    return external_paths


def get_external(file) -> List[str]:
    p = Path(file)

    subtitles = [
        str(sub_p) for sub_p in p.parent.glob(p.stem + "*") if sub_p.suffix[1:].lower() in SUBTITLE_FORMATS.split("|")
    ]

    if subtitles:
        return subtitles

    return []


def get_subtitle_paths(f) -> List[str]:
    internal_subtitles = externalize_internal_subtitles(f)
    if len(internal_subtitles) > 0:
        return internal_subtitles

    external_subtitles = get_external(f)
    return external_subtitles


def get_sub_index(args, f) -> Optional[int]:
    streams = ffmpeg.probe(f)["streams"]
    temp_db = db.connect(args, memory=True)
    temp_db["streams"].insert_all(streams, pk="index")  # type: ignore
    subtitle_index = temp_db.pop(
        f"""select "index" from streams
            where codec_type = "subtitle"
              and codec_name not in ({",".join(['?'] * len(IMAGE_SUBTITLE_CODECS))})
            order by
                lower(tags) like "%eng%" desc
                , lower(tags) like "%en%" desc
                , lower(tags) like "%dialog%" desc
            limit 1""",
        [*IMAGE_SUBTITLE_CODECS],
    )
    return subtitle_index
