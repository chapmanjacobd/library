import errno, os, random, re, shutil, string, sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import gettempdir
from typing import Literal


def now():
    return int(datetime.now(tz=timezone.utc).timestamp())


PYTEST_RUNNING = "pytest" in sys.modules


def today_stamp():
    if PYTEST_RUNNING:
        dt = datetime.now(tz=timezone.utc)
    else:
        dt = datetime.now().astimezone()

    return int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def random_string() -> str:
    return "".join(
        random.choices(string.ascii_uppercase, k=1) + random.choices(string.ascii_uppercase + string.digits, k=4),
    )


TEMP_DIR = str(Path(gettempdir()).resolve())
TEMP_SCRIPT_DIR = os.getenv("XDG_RUNTIME_DIR") or TEMP_DIR
CAST_NOW_PLAYING = str(Path(TEMP_DIR) / "catt_playing")
SUB_TEMP_DIR = str(Path(TEMP_DIR) / "library_temp_subtitles" / random_string())
DEFAULT_MPV_LISTEN_SOCKET = str(Path(TEMP_SCRIPT_DIR) / "mpv_socket")
DEFAULT_MPV_WATCH_SOCKET = str(Path("~/.config/mpv/socket").expanduser().resolve())

mpv_dir = Path("~/.local/state/mpv/watch_later/").expanduser().resolve()
if mpv_dir.exists():
    DEFAULT_MPV_WATCH_LATER = str(mpv_dir)
else:
    DEFAULT_MPV_WATCH_LATER = str(Path("~/.config/mpv/watch_later/").expanduser().resolve())

LOG_INFO = 1
LOG_DEBUG = 2
LOG_DEBUG_SQL = 3
SIMILAR = 1
SIMILAR_NO_FILTER = 2
SIMILAR_NO_FILTER_NO_FTS = 3
SIMILAR_NO_FILTER_NO_FTS_PARENT = 4
RELATED = 1
RELATED_NO_FILTER = 2
DIRS = 1
DIRS_NO_FILTER = 2

DEFAULT_PLAYLIST_LIMIT = 20_000
DEFAULT_FILE_ROWS_READ_LIMIT = 500_000
SQLITE_PARAM_LIMIT = 32766
DEFAULT_PLAY_QUEUE = 120
DEFAULT_MULTIPLE_PLAYBACK = -1
DEFAULT_SUBTITLE_MIX = 0.35
MANY_LINKS = 8
VOLKSWAGEN = "CI" in os.environ
REGEX_ANSI_ESCAPE = re.compile(r"(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]")
REGEX_SUBREDDIT = re.compile("|".join([r".*reddit\.com/r/(.*?)/.*", r".*redd\.it/r/(.*?)/.*"]))
REGEX_REDDITOR = re.compile(
    "|".join(
        [
            r".*reddit\.com/u/(.*?)/.*",
            r".*redd\.it/u/(.*?)/.*",
            r".*reddit\.com/user/(.*?)/.*",
            r".*redd\.it/user/(.*?)/.*",
        ],
    ),
)
REGEX_V_REDD_IT = re.compile("https?://v.redd.it/(?:[^/?#&]+)")
APPLICATION_START = now()
TERMINAL_SIZE = shutil.get_terminal_size(fallback=(80, 60))
MOBILE_TERMINAL = TERMINAL_SIZE.columns < 80
TABULATE_STYLE = "simple"
DEFAULT_DIFFLIB_RATIO = 0.73
DEFAULT_MIN_SPLIT = "90s"
IS_LINUX = sys.platform == "linux"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt" or sys.platform in ("win32", "cygwin", "msys")
NOT_WINDOWS = os.name == "posix"
REQUESTS_TIMEOUT = (8, 45)

EPOCH_COLUMNS = (
    "time_downloaded",  # APPLICATION_START time local file known to exist / time scanned
    "time_deleted",  # APPLICATION_START time local file known to not exist
    "time_created",  # earliest valid time of media creation
    "time_modified",  # time of attempted download, file modification
    "time_played",  # -- history table --
    "time_first_played",  # generated at runtime
    "time_last_played",  # generated at runtime
    "time_valid",  # generated at runtime
)


class DBType:
    audio = "audio"
    video = "video"
    filesystem = "filesystem"
    text = "text"
    image = "image"


class SC:
    fs_add = "fs-add"
    fs_update = "fs-update"
    filesystem = "filesystem"
    media = "media"
    watch = "watch"
    listen = "listen"
    tube_add = "tube-add"
    tube_update = "tube-update"
    reddit_add = "reddit-add"
    reddit_update = "reddit-update"
    gallery_add = "gallery-add"
    gallery_update = "gallery-update"
    tabs_open = "tabs-open"
    links_open = "links-open"
    links_add = "links-add"
    links_update = "links-update"
    read = "read"
    view = "view"
    download = "download"
    block = "block"
    stats = "stats"
    playlists = "playlists"
    download_status = "download-status"
    search = "search"
    history = "history"
    big_dirs = "big-dirs"
    similar_folders = "similar-folders"
    similar_files = "similar-files"
    disk_usage = "disk-usage"
    dedupe_media = "dedupe"
    web_add = "web-add"
    web_update = "web-update"


EnvironmentErrors = (
    errno.ENOSPC,
    errno.ENOENT,
    errno.EIO,
    errno.EROFS,
    errno.ESPIPE,
    errno.EMFILE,
    errno.EPIPE,
    errno.ENAMETOOLONG,
    errno.ENOTEMPTY,
)


class DLStatus:
    SUCCESS = "SUCCESS"
    RECOVERABLE_ERROR = "RECOVERABLE_ERROR"
    UNRECOVERABLE_ERROR = "UNRECOVERABLE_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


def reddit_frequency(frequency) -> str:
    mapper = {
        "daily": "day",
        "weekly": "week",
        "monthly": "month",
        "quarterly": "year",
        "yearly": "year",
    }

    return mapper[frequency]


SKIP_MEDIA_CHECK = ["iso", "img", "vob"]

SPEECH_RECOGNITION_EXTENSIONS = set("mp3|ogg|wav".split("|"))
OCR_EXTENSIONS = set("gif|jpg|jpeg|png|tif|tff|tiff".split("|"))
OCRMYPDF_EXTENSIONS = set("gif|jpg|jpeg|png|tif|tff|tiff|pdf".split("|"))
AUDIO_ONLY_EXTENSIONS = set(
    "mka|opus|oga|ogg|mp3|mpga|m2a|m4a|m4b|flac|wav|aif|aiff|wma|aac|aa3|ac3|ape|mid|midi".split("|")
)
VIDEO_EXTENSIONS = set(
    (
        "str|aa|aax|acm|adf|adp|dtk|ads|ss2|adx|aea|afc|aix|al|apl|avifs|gif|gifv"
        "|mac|aptx|aptxhd|aqt|ast|obu|avi|avr|avs|avs2|avs3|bfstm|bcstm|binka"
        "|bit|bmv|brstm|cdg|cdxl|xl|c2|302|daud|str|adp|dav|dss|dts|dtshd|dv"
        "|dif|divx|cdata|eac3|paf|fap|flm|flv|fsb|fwse|g722|722|tco|rco|heics"
        "|g723_1|g729|genh|gsm|h261|h26l|h264|264|avc|mts|m2ts|hca|hevc|h265|265|idf"
        "|ifv|cgi|ipu|sf|ircam|ivr|kux|669|abc|amf|ams|dbm|dmf|dsm|far|it|mdl"
        "|med|mod|mt2|mtm|okt|psm|ptm|s3m|stm|ult|umx|xm|itgz|itr|itz|iso|img"
        "|mdgz|mdr|mdz|s3gz|s3r|s3z|xmgz|xmr|xmz|669|amf|ams|dbm|digi|dmf"
        "|dsm|dtm|far|gdm|ice|imf|it|j2b|m15|mdl|med|mmcmp|mms|mo3|mod|mptm"
        "|mt2|mtm|nst|okt|ogm|ogv|plm|ppm|psm|pt36|ptm|s3m|sfx|sfx2|st26|stk|stm"
        "|stp|ult|umx|wow|xm|xpk|flv|dat|lvf|m4v|mkv|ts|tp|mk3d|webm|mca|mcc"
        "|mjpg|mjpeg|mpg|mpeg|mpo|j2k|mlp|mods|moflex|mov|mp4|3g2|3gp2|3gp|3gpp|3g2|mj2|psp"
        "|ism|ismv|isma|f4v|mp2|mpa|mpc|mjpg|mpl2|msf|mtaf|ul|musx|mvi|mxg"
        "|v|nist|sph|nsp|nut|obu|oma|omg|pjs|pvf|yuv|cif|qcif|rgb|rt|rsd|rmvb|rm"
        "|rsd|rso|sw|sb|sami|sbc|msbc|sbg|scc|sdr2|sds|sdx|ser|sga|shn|vb|son|imx"
        "|sln|mjpg|stl|sup|svag|svs|tak|thd|tta|ans|art|asc|diz|ice|vt|ty|ty+|uw|ub"
        "|v210|yuv10|vag|vc1|rcv|vob|viv|vpk|vqf|vql|vqe|wmv|wsd|xmv|xvag|yop|y4m"
    ).split("|")
)
SUBTITLE_EXTENSIONS = set("srt|vtt|mks".split("|"))
TEXTRACT_EXTENSIONS = set(
    "csv|tab|tsv|doc|docx|eml|epub|json|htm|html|msg|odt|pdf|pptx|ps|rtf|txt|log|xlsx|xls".split("|")
)
IMAGE_EXTENSIONS = set(
    (
        "ai|ait|png|jng|mng|arq|arw|cr2|cs1|dcp|dng|eps|epsf|ps|erf|exv|fff"
        "|gpr|hdp|wdp|jxr|iiq|insp|jpeg|jpg|jpe|mef|mie|mos|mpo|mrw|nef|nrw|orf"
        "|ori|pef|psd|psb|psdt|raf|raw|rw2|rwl|sr2|srw|thm|tiff|tif|x3f|flif|gif"
        "|icc|icm|avif|heic|heif|hif|jp2|jpf|jpm|jpx|j2c|j2k|jpc|3fr|btf|dcr|k25"
        "|kdc|miff|mif|rwz|srf|xcf|bpg|doc|dot|fla|fpx|max|ppt|pps|pot|vsd|xls"
        "|xlt|pict|pct|360|aax|dvb|f4a|f4b|f4p|f4v|lrv|m4b"
        "|m4p|qt|mqv|qtif|qti|qif|cr3|crm|jxl|crw|ciff|ind|indd|indt"
        "|nksc|vrd|xmp|la|ofr|pac|riff|rif|wav|webp|wv|asf|divx|djvu|djv|dvr-ms"
        "|flv|insv|inx|swf|wma|wmv|exif|eip|psp|pspimage"
    ).split("|")
)
PIL_EXTENSIONS = set(
    (
        "apng|blp|bmp|bufr|bw|cur|dcx|dds|dib|emf|eps|fit|fits|flc|fli|fpx|ftc"
        "|ftex|ftu|gbr|gd|gif|grib|h5|hdf|icb|icns|ico|iim|im|imt|iptc|j2c|j2k"
        "|jfif|jp2|jpc|jpe|jpeg|jpf|jpg|jpx|mcidas|mic|mpeg|mpg|mpo|msp|naa|palm"
        "|pbm|pcd|pcx|pdf|pfm|pgm|pixar|png|pnm|ppm|ps|psd|pxr|qoi|ras|rgb|rgba"
        "|sgi|spi|spider|sun|tga|tif|tiff|vda|vst|wal|webp|wmf|xbm|xpm"
    ).split("|")
)
IMAGE_ANIMATION_EXTENSIONS = set(("gif|png|apng|webp|avif|avifs|flif|mng").split("|"))
ARCHIVE_EXTENSIONS = set(
    (
        "0|1|01|001|0001|7z|ace|alz|alzip|arc|arj|b5i|b6i|bin|bz2|cab|ccd|cdr|cif"
        "|cpio|daa|deb|dmg|exe|gi|gz|img|iso|lha|lzh|lzma|lzo|mdf|msi|nrg|nsi|nsis"
        "|p01|pak|pdi|r00|rar|rpm|sit|sitx|tar|bz2|gz|xz|Z|taz|tbz2|tgz|toast|txz"
        "|tz|udf|uif|vcd|wim|xar|xz|z|zip|zipx|zoo|zst|cb7|cbr|cbz|cbt|cba"
    ).split("|")
)
CALIBRE_EXTENSIONS = set(
    ("azw|azw3|azw4|cbc|chm|docx|epub|fb2|fbz|htmlz|lit|lrf|mobi|odt|pdf|prc|pdb|pml|rb|rtf|snb|tcr|md|txtz").split("|")
)
PLAIN_EXTENSIONS = set(
    ("xml|opf|html|xhtml|txt|text|md|markdown|css|js|json|csv|yaml|toml|ini|rst|cfg|conf").split("|")
)

time_facets = [
    "watching",
    "watched",
    "listened",
    "listening",
    "heard",
    "seen",
    "deleted",
    "created",
    "modified",
    "downloaded",
]

frequency = ["minutely", "hourly", "daily", "weekly", "monthly", "quarterly", "yearly", "decadally"]


PLAYLIST_KNOWN_KEYS = ("description", "url", "duration", "view_count", "webpage_url", "original_url", "time_deleted")

MEDIA_KNOWN_KEYS = (
    "cookies",
    "PURL",
    "cast",
    "channel_is_verified",
    "album_artist",
    "downloader_options_http_chunk_size",
    "heatmap",
    "expected_protocol",
    "photoset_layout",
    "asks_allow_media",
    "submission_page_title",
    "post_author_is_adult",
    "is_submission",
    "fragment",
    "fragment_base_url",
    "direct",
    "is_anonymous",
    "ask",
    "ask_anon",
    "ask_page_title",
    "avatar",
    "theme",
    "count",
    "can_chat",
    "can_subscribe",
    "share_likes",
    "subscribed",
    "total_posts",
    "is_blocks_post_format",
    "blog_name",
    "id_string",
    "is_blazed",
    "is_blaze_pending",
    "can_blaze",
    "slug",
    "state",
    "reblog_key",
    "short_url",
    "summary",
    "should_open_in_legacy",
    "note_count",
    "caption",
    "reblog",
    "can_like",
    "interactability_reblog",
    "interactability_blaze",
    "can_reblog",
    "can_send_in_message",
    "can_reply",
    "display_avatar",
    "reblogged",
    "hash",
    "link_url",
    "query",
    "domain",
    "etag",
    "pages",
    "posts",
    "locale",
    "num",
    "kind",
    "ie_key",
    "extractor_key",
    "extractor",
    "upvote_count",
    "downvote_count",
    "filename",
    "extension",
    "category",
    "subcategory",
    "virality",
    "in_most_viral",
    "is_album",
    "is_mature",
    "cover_id",
    "image_count",
    "privacy",
    "vote",
    "favorite",
    "is_ad",
    "include_album_ads",
    "shared_with_community",
    "is_pending",
    "display",
    "mime_type",
    "type",
    "name",
    "basename",
    "is_animated",
    "is_looping",
    "has_sound",
    "platform",
    "track_id",
    "track_number",
    "repost_count",
    "fragments",
    "thumbnail",
    "thumbnails",
    "availability",
    "playable_in_embed",
    "is_live",
    "was_live",
    "modified_date",
    "aspect_ratio",
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
    "duration",
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
    "playlists_id",
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
    "entries",
    "dislike_count",
    "manifest_url",
    "manifest_stream_number",
    "start_time",
)

COMMON_ENCODINGS = [
    "Windows-1252",
    "utf-16",
    "utf-16-le",
    "Windows-1251",
    "GB18030",
    "big5",
    "Shift-JIS",
    "euc-jp",
    "Windows-1250",
    "Windows-1256",
    "CP949",
    "Windows-1253",
    "Windows-1255",
    "Windows-1254",
    "Windows-1257",
    "utf-32",
    "utf-16-be",
    "utf-32-le",
    "utf-32-be",
]

WordSortOpt = Literal[
    "skip",
    "len",
    "count",
    "dup",
    "unique",
    "index",
    "lastindex",
    "linecount",
    "alpha",
    "natural",
    "natsort",
    "path",
    "locale",
    "signed",
    "os",
    "mcda",
]

LineSortOpt = Literal[
    "skip",
    "line",
    "count",
    "len",
    "sum",
    "unique",
    "allunique",
    "alluniques",
    "dup",
    "alldup",
    "alldups",
    "dupmax",
    "dupavg",
    "dupmin",
    "dupmedian",
    "dupmode",
    "alpha",
    "natural",
    "natsort",
    "path",
    "locale",
    "signed",
    "os",
    "mcda",
]
