import argparse
import logging
import os
import sys
from functools import wraps
from glob import glob
from pathlib import Path
from subprocess import PIPE, run

from IPython.core import ultratb
from IPython.terminal.debugger import TerminalPdb
from rich import inspect, print
from rich.logging import RichHandler


def get_video_files(args):
    FFMPEG_DEMUXERS = "str|aa|aac|aax|ac3|acm|adf|adp|dtk|ads|ss2|adx|aea|afc|aix|al|ape|apl|mac|aptx|aptxhd|aqt|ast|obu|avi|avr|avs|avs2|avs3|bfstm|bcstm|binka|bit|bmv|brstm|cdg|cdxl|xl|c2|302|daud|str|adp|dav|dss|dts|dtshd|dv|dif|cdata|eac3|paf|fap|flm|flac|flv|fsb|fwse|g722|722|tco|rco|g723_1|g729|genh|gsm|h261|h26l|h264|264|avc|hca|hevc|h265|265|idf|ifv|cgi|ipu|sf|ircam|ivr|kux|669|abc|amf|ams|dbm|dmf|dsm|far|it|mdl|med|mid|mod|mt2|mtm|okt|psm|ptm|s3m|stm|ult|umx|xm|itgz|itr|itz|mdgz|mdr|mdz|s3gz|s3r|s3z|xmgz|xmr|xmz|669|amf|ams|dbm|digi|dmf|dsm|dtm|far|gdm|ice|imf|it|j2b|m15|mdl|med|mmcmp|mms|mo3|mod|mptm|mt2|mtm|nst|okt|plm|ppm|psm|pt36|ptm|s3m|sfx|sfx2|st26|stk|stm|stp|ult|umx|wow|xm|xpk|flv|dat|lvf|m4v|mkv|mk3d|mka|mks|webm|mca|mcc|mjpg|mjpeg|mpo|j2k|mlp|mods|moflex|mov|mp4|m4a|3gp|3g2|mj2|psp|m4b|ism|ismv|isma|f4v|mp2|mp3|m2a|mpa|mpc|mjpg|txt|mpl2|msf|mtaf|ul|musx|mvi|mxg|v|nist|sph|nsp|nut|obu|ogg|oma|omg|aa3|pjs|pvf|yuv|cif|qcif|rgb|rt|rsd|rsd|rso|sw|sb|sami|sbc|msbc|sbg|scc|sdr2|sds|sdx|ser|sga|shn|vb|son|imx|sln|mjpg|stl|sup|svag|svs|tak|thd|tta|ans|art|asc|diz|ice|txt|vt|ty|ty+|uw|ub|v210|yuv10|vag|vc1|rcv|viv|vpk|txt|vqf|vql|vqe|vtt|wsd|xmv|xvag|yop|y4m|opus|oga".split(
        "|"
    )

    video_files = []
    for path in args.paths:
        for f in Path(path).resolve().rglob("*"):
            if f.is_file() and (f.suffix.lower()[1:] in FFMPEG_DEMUXERS):
                video_files.append(str(f))

    return video_files


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
    print(args)

    try:
        if args.verbose > 0 and os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno()):
            sys.excepthook = ultratb.FormattedTB(
                mode="Verbose" if args.verbose > 1 else "Context",
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


def cmd(command, strict=True, cwd=None):
    r = run(command, capture_output=True, text=True, shell=True, cwd=cwd)
    log.debug(r.args)
    if len(r.stdout.strip()) > 0:
        log.debug(r.stdout.strip())
    if len(r.stderr.strip()) > 0:
        log.error(r.stderr.strip())
    if r.returncode != 0:
        log.debug(f"ERROR {r.returncode}")
        if strict:
            raise Exception(r.returncode)
    return r
