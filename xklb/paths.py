import enum, os, platform, re
from pathlib import Path
from tempfile import gettempdir, mkdtemp
from typing import List

from xklb import utils

FAKE_SUBTITLE = os.path.join(gettempdir(), "sub.srt")  # https://github.com/skorokithakis/catt/issues/393
CAST_NOW_PLAYING = os.path.join(gettempdir(), "catt_playing")
DEFAULT_MPV_SOCKET = os.path.join(gettempdir(), "mpv_socket")
DEFAULT_MPV_WATCH_LATER = os.path.expanduser("~/.config/mpv/watch_later/")
SUB_TEMP_DIR = mkdtemp()
BLOCK_THE_CHANNEL = "__BLOCKLIST_ENTRY_"


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
    matches = re.match(r".*reddit.com/r/(.*?)/.*", path)
    if matches:
        subreddit = matches.groups()[0]
        return "https://old.reddit.com/r/" + subreddit + "/top/?sort=top&t=" + reddit_frequency(args.frequency)

    if "m.youtube" in path:
        return path.replace("m.youtube", "www.youtube")

    return path


def youtube_dl_id(file) -> str:
    if len(file) < 15:
        return ""
    # rename old youtube_dl format to new one: cargo install renamer; fd -tf . -x renamer '\-([\w\-_]{11})\.= [$1].' {}
    yt_id_regex = re.compile(r"-([\w\-_]{11})\..*$|\[([\w\-_]{11})\]\..*$", flags=re.M)
    file = str(file).strip()

    yt_ids = yt_id_regex.findall(file)
    if len(yt_ids) == 0:
        return ""

    return utils.conform([*yt_ids[0]])[0]


def get_text_files(path, OCR=False, speech_recognition=False) -> List[str]:
    TEXTRACT_EXTENSIONS = "csv|tab|tsv|doc|docx|eml|epub|json|htm|html|msg|odt|pdf|pptx|ps|rtf|txt|log|xlsx|xls"
    if OCR:
        ocr_only = "|gif|jpg|jpeg|png|tif|tff|tiff"
        TEXTRACT_EXTENSIONS += ocr_only
    if speech_recognition:
        speech_recognition_only = "|mp3|ogg|wav"
        TEXTRACT_EXTENSIONS += speech_recognition_only

    TEXTRACT_EXTENSIONS = TEXTRACT_EXTENSIONS.split("|")
    text_files = []
    for f in Path(path).resolve().rglob("*"):
        if f.is_file() and (f.suffix[1:].lower() in TEXTRACT_EXTENSIONS):
            text_files.append(str(f))

    return text_files


def get_media_files(path, audio=False) -> List[str]:
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
    for f in Path(path).resolve().rglob("*"):
        if f.is_file() and (f.suffix[1:].lower() in FFMPEG_EXTENSIONS):
            media_files.append(str(f))

    return media_files


def get_image_files(path) -> List[str]:
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
    for f in Path(path).resolve().rglob("*"):
        if f.is_file() and (f.suffix[1:].lower() in IMAGE_EXTENSIONS):
            image_files.append(str(f))

    return image_files


def is_mounted(paths, mount_point) -> bool:
    if platform.system() == "Linux" and any([mount_point in p for p in paths]):
        p = Path(mount_point)
        if p.exists() and not p.is_mount():
            raise Exception(f"mount_point {mount_point} not mounted yet")

    return True
