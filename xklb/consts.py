import enum, os, re, sys
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir, mkdtemp
from types import SimpleNamespace
from typing import List

FAKE_SUBTITLE = os.path.join(gettempdir(), "sub.srt")  # https://github.com/skorokithakis/catt/issues/393
CAST_NOW_PLAYING = os.path.join(gettempdir(), "catt_playing")
DEFAULT_MPV_SOCKET = os.path.join(gettempdir(), "mpv_socket")
DEFAULT_MPV_WATCH_LATER = os.path.expanduser("~/.config/mpv/watch_later/")
SUB_TEMP_DIR = mkdtemp()
BLOCK_THE_CHANNEL = "__BLOCKLIST_ENTRY_"

SQLITE_PARAM_LIMIT = 32765
DEFAULT_PLAY_QUEUE = 120
DEFAULT_MULTIPLE_PLAYBACK = -1
CPU_COUNT = int(os.cpu_count() or 4)
PYTEST_RUNNING = "pytest" in sys.modules
REGEX_ANSI_ESCAPE = re.compile(r"(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]")
REGEX_SUBREDDIT = re.compile("|".join([r".*reddit\.com/r/(.*?)/.*", r".*redd\.it/r/(.*?)/.*"]))
REGEX_REDDITOR = re.compile(
    "|".join(
        [
            r".*reddit\.com/u/(.*?)/.*",
            r".*redd\.it/u/(.*?)/.*",
            r".*reddit\.com/user/(.*?)/.*",
            r".*redd\.it/user/(.*?)/.*",
        ]
    )
)
NOW = int(datetime.now().timestamp())

try:
    TERMINAL_SIZE = os.get_terminal_size()
except Exception:
    TERMINAL_SIZE = SimpleNamespace(columns=80, lines=60)


TIME_COLUMNS = (
    "time_downloaded",
    "time_deleted",
    "time_modified",
    "time_created",
    "time_played",
    "time_valid",
    "time_partial_first",
    "time_partial_last",
)


class DBType:
    audio = "audio"
    video = "video"
    filesystem = "filesystem"
    text = "text"
    image = "image"


class SC:
    fsadd = "fsadd"
    fsupdate = "fsupdate"
    watch = "watch"
    listen = "listen"
    filesystem = "filesystem"
    tubeadd = "tubeadd"
    tubeupdate = "tubeupdate"
    tabs = "tabs"
    read = "read"
    view = "view"
    download = "download"
    block = "block"
    galyadd = "galyadd"
    galyupdate = "galyupdate"


class Frequency(enum.Enum):
    Daily = "daily"
    Weekly = "weekly"
    Monthly = "monthly"
    Quarterly = "quarterly"
    Yearly = "yearly"


def reddit_frequency(frequency: Frequency) -> str:
    mapper = {
        Frequency.Daily: "day",
        Frequency.Weekly: "week",
        Frequency.Monthly: "month",
        Frequency.Quarterly: "year",
        Frequency.Yearly: "year",
    }

    return mapper.get(frequency, "month")


def sanitize_url(args, path: str) -> str:
    matches = REGEX_SUBREDDIT.match(path)
    if matches:
        subreddit = matches.groups()[0]
        return "https://old.reddit.com/r/" + subreddit + "/top/?sort=top&t=" + reddit_frequency(args.frequency)

    if "/m." in path:
        return path.replace("/m.", "/www.")

    return path


def get_text_files(path: Path, OCR=False, speech_recognition=False) -> List[str]:
    TEXTRACT_EXTENSIONS = "csv|tab|tsv|doc|docx|eml|epub|json|htm|html|msg|odt|pdf|pptx|ps|rtf|txt|log|xlsx|xls"
    if OCR:
        ocr_only = "|gif|jpg|jpeg|png|tif|tff|tiff"
        TEXTRACT_EXTENSIONS += ocr_only
    if speech_recognition:
        speech_recognition_only = "|mp3|ogg|wav"
        TEXTRACT_EXTENSIONS += speech_recognition_only

    TEXTRACT_EXTENSIONS = TEXTRACT_EXTENSIONS.split("|")
    text_files = []
    for f in path.rglob("*"):
        if f.is_file() and (f.suffix[1:].lower() in TEXTRACT_EXTENSIONS):
            text_files.append(str(f))

    return text_files


def get_media_files(path: Path, audio=False) -> List[str]:
    FFMPEG_EXTENSIONS = (
        "str|aa|aax|acm|adf|adp|dtk|ads|ss2|adx|aea|afc|aix|al|apl"
        "|mac|aptx|aptxhd|aqt|ast|obu|avi|avr|avs|avs2|avs3|bfstm|bcstm|binka"
        "|bit|bmv|brstm|cdg|cdxl|xl|c2|302|daud|str|adp|dav|dss|dts|dtshd|dv"
        "|dif|cdata|eac3|paf|fap|flm|flv|fsb|fwse|g722|722|tco|rco"
        "|g723_1|g729|genh|gsm|h261|h26l|h264|264|avc|hca|hevc|h265|265|idf"
        "|ifv|cgi|ipu|sf|ircam|ivr|kux|669|abc|amf|ams|dbm|dmf|dsm|far|it|mdl"
        "|med|mid|mod|mt2|mtm|okt|psm|ptm|s3m|stm|ult|umx|xm|itgz|itr|itz"
        "|mdgz|mdr|mdz|s3gz|s3r|s3z|xmgz|xmr|xmz|669|amf|ams|dbm|digi|dmf"
        "|dsm|dtm|far|gdm|ice|imf|it|j2b|m15|mdl|med|mmcmp|mms|mo3|mod|mptm"
        "|mt2|mtm|nst|okt|plm|ppm|psm|pt36|ptm|s3m|sfx|sfx2|st26|stk|stm"
        "|stp|ult|umx|wow|xm|xpk|flv|dat|lvf|m4v|mkv|mk3d|mka|mks|webm|mca|mcc"
        "|mjpg|mjpeg|mpo|j2k|mlp|mods|moflex|mov|mp4|3gp|3g2|mj2|psp|m4b"
        "|ism|ismv|isma|f4v|mp2|mpa|mpc|mjpg|mpl2|msf|mtaf|ul|musx|mvi|mxg"
        "|v|nist|sph|nsp|nut|obu|oma|omg|pjs|pvf|yuv|cif|qcif|rgb|rt|rsd"
        "|rsd|rso|sw|sb|sami|sbc|msbc|sbg|scc|sdr2|sds|sdx|ser|sga|shn|vb|son|imx"
        "|sln|mjpg|stl|sup|svag|svs|tak|thd|tta|ans|art|asc|diz|ice|vt|ty|ty+|uw|ub"
        "|v210|yuv10|vag|vc1|rcv|viv|vpk|vqf|vql|vqe|wsd|xmv|xvag|yop|y4m"
    )
    if audio:
        audio_only = "|opus|oga|ogg|mp3|m2a|m4a|flac|wav|wma|aac|aa3|ac3|ape"
        FFMPEG_EXTENSIONS += audio_only

    FFMPEG_EXTENSIONS = FFMPEG_EXTENSIONS.split("|")
    media_files = []
    for f in path.rglob("*"):
        if f.is_file() and (f.suffix[1:].lower() in FFMPEG_EXTENSIONS):
            media_files.append(str(f))

    return media_files


def get_image_files(path: Path) -> List[str]:
    IMAGE_EXTENSIONS = (
        "pdf|ai|ait|png|jng|mng|arq|arw|cr2|cs1|dcp|dng|eps|epsf|ps|erf|exv|fff"
        "|gpr|hdp|wdp|jxr|iiq|insp|jpeg|jpg|jpe|mef|mie|mos|mpo|mrw|nef|nrw|orf"
        "|ori|pef|psd|psb|psdt|raf|raw|rw2|rwl|sr2|srw|thm|tiff|tif|x3f|flif|gif"
        "|icc|icm|avif|heic|heif|hif|jp2|jpf|jpm|jpx|j2c|j2k|jpc|3fr|btf|dcr|k25"
        "|kdc|miff|mif|rwz|srf|xcf|bpg|doc|dot|fla|fpx|max|ppt|pps|pot|vsd|xls"
        "|xlt|pict|pct|360|3g2|3gp2|3gp|3gpp|aax|dvb|f4a|f4b|f4p|f4v|lrv|m4b"
        "|m4p|m4v|mov|qt|mqv|qtif|qti|qif|cr3|crm|jxl|crw|ciff|ind|indd|indt"
        "|nksc|vrd|xmp|la|ofr|pac|riff|rif|wav|webp|wv|asf|divx|djvu|djv|dvr-ms"
        "|flv|insv|inx|swf|wma|wmv|exif|eip|psp|pspimage"
    )

    IMAGE_EXTENSIONS = IMAGE_EXTENSIONS.split("|")
    image_files = []
    for f in path.rglob("*"):
        if f.is_file() and (f.suffix[1:].lower() in IMAGE_EXTENSIONS):
            image_files.append(str(f))

    return image_files


TUBE_IGNORE_KEYS = (
    "thumbnail",
    "thumbnails",
    "availability",
    "playable_in_embed",
    "is_live",
    "was_live",
    "modified_date",
    "release_timestamp",
    "comment_count",
    "chapters",
    "like_count",
    "channel_follower_count",
    "webpage_url_basename",
    "webpage_url_domain",
    "playlist",
    "playlist_index",
    "display_id",
    "fulltitle",
    "duration_string",
    "format",
    "format_id",
    "ext",
    "protocol",
    "format_note",
    "tbr",
    "resolution",
    "dynamic_range",
    "vcodec",
    "vbr",
    "stretched_ratio",
    "acodec",
    "abr",
    "asr",
    "epoch",
    "license",
    "timestamp",
    "track",
    "comments",
    "author",
    "text",
    "parent",
    "root",
    "filesize",
    "source_preference",
    "video_ext",
    "audio_ext",
    "http_headers",
    "User-Agent",
    "Accept",
    "Accept-Language",
    "Sec-Fetch-Mode",
    "navigate",
    "Cookie",
    "playlist_count",
    "n_entries",
    "playlist_autonumber",
    "availability",
    "formats",
    "requested_formats",
    "requested_entries",
    "requested_downloads",
    "thumbnails",
    "playlist_count",
    "playlist_id",
    "playlist_title",
    "playlist_uploader",
    "audio_channels",
    "subtitles",
    "automatic_captions",
    "quality",
    "has_drm",
    "language_preference",
    "preference",
    "location",
    "downloader_options",
    "container",
    "local_path",
    "album",
    "artist",
    "release_year",
    "creator",
    "alt_title",
    "format_index",
    "requested_subtitles",
)
