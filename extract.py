import argparse
import json
import os
import sys
from datetime import datetime
from glob import glob
from shlex import quote

import pandas as pd
from joblib import Parallel, delayed
from rich import inspect, print

from db import con
from utils import cmd

parser = argparse.ArgumentParser()
parser.add_argument("path")
args = parser.parse_args()

FFMPEG_DEMUXERS = "str|aa|aac|aax|ac3|acm|adf|adp|dtk|ads|ss2|adx|aea|afc|aix|al|ape|apl|mac|aptx|aptxhd|aqt|ast|obu|avi|avr|avs|avs2|avs3|bfstm|bcstm|binka|bit|bmv|brstm|cdg|cdxl|xl|c2|302|daud|str|adp|dav|dss|dts|dtshd|dv|dif|cdata|eac3|paf|fap|flm|flac|flv|fsb|fwse|g722|722|tco|rco|g723_1|g729|genh|gsm|h261|h26l|h264|264|avc|hca|hevc|h265|265|idf|ifv|cgi|ipu|sf|ircam|ivr|kux|669|abc|amf|ams|dbm|dmf|dsm|far|it|mdl|med|mid|mod|mt2|mtm|okt|psm|ptm|s3m|stm|ult|umx|xm|itgz|itr|itz|mdgz|mdr|mdz|s3gz|s3r|s3z|xmgz|xmr|xmz|669|amf|ams|dbm|digi|dmf|dsm|dtm|far|gdm|ice|imf|it|j2b|m15|mdl|med|mmcmp|mms|mo3|mod|mptm|mt2|mtm|nst|okt|plm|ppm|psm|pt36|ptm|s3m|sfx|sfx2|st26|stk|stm|stp|ult|umx|wow|xm|xpk|flv|dat|lvf|m4v|mkv|mk3d|mka|mks|webm|mca|mcc|mjpg|mjpeg|mpo|j2k|mlp|mods|moflex|mov|mp4|m4a|3gp|3g2|mj2|psp|m4b|ism|ismv|isma|f4v|mp2|mp3|m2a|mpa|mpc|mjpg|txt|mpl2|sub|msf|mtaf|ul|musx|mvi|mxg|v|nist|sph|nsp|nut|obu|ogg|oma|omg|aa3|pjs|pvf|yuv|cif|qcif|rgb|rt|rsd|rsd|rso|sw|sb|smi|sami|sbc|msbc|sbg|scc|sdr2|sds|sdx|ser|sga|shn|vb|son|imx|sln|mjpg|stl|sub|sub|sup|svag|svs|tak|thd|tta|ans|art|asc|diz|ice|nfo|txt|vt|ty|ty+|uw|ub|v210|yuv10|vag|vc1|rcv|viv|idx|vpk|txt|vqf|vql|vqe|vtt|wsd|xmv|xvag|yop|y4m|opus|oga"

video_files = []
for ext in FFMPEG_DEMUXERS.split("|"):
    default_glob = glob(args.path + "/*" + ext, recursive=True) + glob(
        args.path + "*" + ext, recursive=True
    )

    if "." in args.path[6:] and len(default_glob) == 0:
        if ext in args.path[6:]:
            video_files.extend(glob(args.path))
    else:
        video_files.extend(default_glob)
video_files = list(set(video_files))

print(video_files)


def extract_metadata(file):
    try:
        ffprobe = json.loads(
            cmd(
                f"ffprobe -loglevel quiet -print_format json=compact=1 -show_entries format {quote(file)}"
            ).stdout
        )
    except:
        print(f"Failed reading {file}", file=sys.stderr)
        return

    if not "format" in ffprobe:
        print(f"Failed reading format {file}", file=sys.stderr)
        print(ffprobe)
        return

    stat = os.stat(file)
    blocks_allocated = stat.st_blocks * 512

    if "tags" in ffprobe["format"]:
        del ffprobe["format"]["tags"]

    return dict(
        **ffprobe["format"],
        # streams=ffprobe["streams"],
        sparseness=int(ffprobe["format"]["size"]) / blocks_allocated,
        time_created=datetime.fromtimestamp(stat.st_ctime),
        time_modified=datetime.fromtimestamp(stat.st_mtime),
    )


metadata = Parallel(n_jobs=-1)(delayed(extract_metadata)(file) for file in video_files)
metadata = list(filter(None, metadata))


pd.DataFrame(metadata).to_sql(
    "videos",
    con=con,
    if_exists="append",
    index=False,
    chunksize=70,
    method="multi",
)
