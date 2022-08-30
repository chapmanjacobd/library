import enum, os, re
from pathlib import Path
from tempfile import gettempdir, mkdtemp

from xklb import utils

FAKE_SUBTITLE = os.path.join(gettempdir(), "sub.srt")  # https://github.com/skorokithakis/catt/issues/393
CAST_NOW_PLAYING = os.path.join(gettempdir(), "catt_playing")
DEFAULT_MPV_SOCKET = os.path.join(gettempdir(), "mpv_socket")
SUB_TEMP_DIR = mkdtemp()


class Frequency(enum.Enum):
    Daily = "daily"
    Weekly = "weekly"
    Monthly = "monthly"
    Quarterly = "quarterly"
    Yearly = "yearly"


def reddit_frequency(frequency: Frequency):
    mapper = {
        Frequency.Daily: "day",
        Frequency.Weekly: "week",
        Frequency.Monthly: "month",
        Frequency.Quarterly: "year",
        Frequency.Yearly: "year",
    }

    return mapper.get(frequency, "month")


def sanitize_url(args, path):
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


def get_media_files(path, audio=False):
    FFMPEG_DEMUXERS = (
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
        FFMPEG_DEMUXERS += audio_only

    FFMPEG_ENDINGS = FFMPEG_DEMUXERS.split("|")
    video_files = []
    for f in Path(path).resolve().rglob("*"):
        if f.is_file() and (f.suffix[1:].lower() in FFMPEG_ENDINGS):
            video_files.append(str(f))

    return video_files
