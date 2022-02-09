from glob import glob
import logging
from subprocess import PIPE, run
import sys
from IPython.core import ultratb


# sys.excepthook = ultratb.FormattedTB(mode="Context", color_scheme="Neutral", call_pdb=1)


def cmd(command, strict=True):
    log = logging.getLogger()
    r = run(command, capture_output=True, text=True, shell=True)
    log.debug(r.args)
    if len(r.stdout.strip()) > 0:
        log.info(r.stdout.strip())
    if len(r.stderr.strip()) > 0:
        log.error(r.stderr.strip())
    if r.returncode != 0:
        log.debug(f"ERROR {r.returncode}")
        if strict:
            raise Exception(r.returncode)
    return r


def get_video_files(args):
    FFMPEG_DEMUXERS = "str|aa|aac|aax|ac3|acm|adf|adp|dtk|ads|ss2|adx|aea|afc|aix|al|ape|apl|mac|aptx|aptxhd|aqt|ast|obu|avi|avr|avs|avs2|avs3|bfstm|bcstm|binka|bit|bmv|brstm|cdg|cdxl|xl|c2|302|daud|str|adp|dav|dss|dts|dtshd|dv|dif|cdata|eac3|paf|fap|flm|flac|flv|fsb|fwse|g722|722|tco|rco|g723_1|g729|genh|gsm|h261|h26l|h264|264|avc|hca|hevc|h265|265|idf|ifv|cgi|ipu|sf|ircam|ivr|kux|669|abc|amf|ams|dbm|dmf|dsm|far|it|mdl|med|mid|mod|mt2|mtm|okt|psm|ptm|s3m|stm|ult|umx|xm|itgz|itr|itz|mdgz|mdr|mdz|s3gz|s3r|s3z|xmgz|xmr|xmz|669|amf|ams|dbm|digi|dmf|dsm|dtm|far|gdm|ice|imf|it|j2b|m15|mdl|med|mmcmp|mms|mo3|mod|mptm|mt2|mtm|nst|okt|plm|ppm|psm|pt36|ptm|s3m|sfx|sfx2|st26|stk|stm|stp|ult|umx|wow|xm|xpk|flv|dat|lvf|m4v|mkv|mk3d|mka|mks|webm|mca|mcc|mjpg|mjpeg|mpo|j2k|mlp|mods|moflex|mov|mp4|m4a|3gp|3g2|mj2|psp|m4b|ism|ismv|isma|f4v|mp2|mp3|m2a|mpa|mpc|mjpg|txt|mpl2|sub|msf|mtaf|ul|musx|mvi|mxg|v|nist|sph|nsp|nut|obu|ogg|oma|omg|aa3|pjs|pvf|yuv|cif|qcif|rgb|rt|rsd|rsd|rso|sw|sb|smi|sami|sbc|msbc|sbg|scc|sdr2|sds|sdx|ser|sga|shn|vb|son|imx|sln|mjpg|stl|sub|sub|sup|svag|svs|tak|thd|tta|ans|art|asc|diz|ice|nfo|txt|vt|ty|ty+|uw|ub|v210|yuv10|vag|vc1|rcv|viv|idx|vpk|txt|vqf|vql|vqe|vtt|wsd|xmv|xvag|yop|y4m|opus|oga"

    video_files = []
    # if args.path.endswith("/"):
    #     args.path = args.path[:-1]
    # if "." in args.path[6:]:
    #     video_files.extend(glob(args.path))
    for path in args.paths:
        for ext in FFMPEG_DEMUXERS.split("|"):
            video_files.extend(glob(path + "/**/*" + ext, recursive=True))
    return video_files
