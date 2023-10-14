import re, tempfile
from pathlib import Path
from typing import List, Optional

import ffmpeg

from xklb.utils import db_utils, iterables, processes, strings
from xklb.utils.consts import SUB_TEMP_DIR
from xklb.utils.log_utils import log

SUBTITLE_FORMATS = "vtt|srt|ssa|ass|jss|aqt|mpl2|mpsub|pjs|rt|sami|smi|stl|xml|txt|psb|ssf|usf"
IMAGE_SUBTITLE_CODECS = ["dvbsub", "dvdsub", "pgssub", "xsub", "dvb_subtitle", "dvd_subtitle", "hdmv_pgs_subtitle"]
SUBSTATION_OVERRIDE_TAG = re.compile(r"{[^}]*}")


def extract_from_video(path, stream_index) -> Optional[str]:
    Path(SUB_TEMP_DIR).mkdir(parents=True, exist_ok=True)
    temp_srt = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)

    stream_id = "0:" + str(stream_index)

    try:
        ffmpeg.input(path).output(temp_srt, map=stream_id).global_args("-nostdin").run(quiet=True)
    except ffmpeg.Error as e:
        log.info(
            f"Could not extract subtitle {stream_id} from video file. Likely incorrect subtitle character encoding set. %s",
            path,
        )
        log.debug(e.stderr.decode())
        return None

    return temp_srt


def convert_to_srt(path) -> str:
    Path(SUB_TEMP_DIR).mkdir(parents=True, exist_ok=True)
    temp_srt = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)
    try:
        ffmpeg.input(path).output(temp_srt).global_args("-nostdin").run(quiet=True)
    except ffmpeg.Error as e:
        log.info("Could not convert subtitle")
        log.info(e.stderr.decode())
        raise UnicodeDecodeError("utf-8", b"Dr. John A. Zoidberg", 1, 2, "Bleh!") from e

    return temp_srt


def ssa_to_markdown(text):
    tag_replacements = {
        r"{\\i1}": "*",  # Italic
        r"{\\b1}": "**",  # Bold
        r"{\\u1}": "<u>",  # Underline
        r"{\\s1}": "~~",  # Strikeout
    }
    for tag, replacement in tag_replacements.items():
        text = re.sub(re.escape(tag), replacement, text)

    text = SUBSTATION_OVERRIDE_TAG.sub("", text)
    text = text.replace(r"\h", " ").replace(r"\n", "\n").replace(r"\N", "\n").replace("\n", " ")
    return text


def read_sub_unsafe(path):
    import pysubs2

    subs = pysubs2.load(path, format_="srt")
    subs.remove_miscellaneous_events()
    subs.sort()

    combined_captions = {}
    for caption in subs:
        text = strings.remove_consecutive_whitespace(ssa_to_markdown(caption.text).strip())
        if strings.remove_text_inside_brackets(text):
            start_time = caption.start // 1000
            if start_time in combined_captions:
                combined_captions[start_time]["text"] += " " + text
            else:
                combined_captions[start_time] = {
                    "time": start_time,
                    "text": text,
                }

    return list(combined_captions.values())


def read_sub(path):
    if Path(path).suffix.lower() != ".srt":
        path = convert_to_srt(path)

    try:
        return read_sub_unsafe(path)
    except UnicodeDecodeError:
        return read_sub_unsafe(convert_to_srt(path))


def is_text_subtitle_stream(s) -> bool:
    return s.get("codec_type") == "subtitle" and s.get("codec_name") not in IMAGE_SUBTITLE_CODECS


def externalize_internal_subtitles(path, streams=None) -> List[str]:
    if streams is None:
        streams = processes.FFProbe(path).streams

    external_paths = iterables.conform(
        [extract_from_video(path, s["index"]) for s in streams if is_text_subtitle_stream(s)],
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


def get_subtitle_paths(path) -> List[str]:
    internal_subtitles = externalize_internal_subtitles(path)
    if len(internal_subtitles) > 0:
        return internal_subtitles

    external_subtitles = get_external(path)
    return external_subtitles


def get_sub_index(args, path) -> Optional[int]:
    probe = processes.FFProbe(path)
    temp_db = db_utils.connect(args, memory=True)
    temp_db["streams"].insert_all(probe.streams, pk="index")  # type: ignore
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
