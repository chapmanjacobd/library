import hashlib
import os
import subprocess
import sys

from xklb.utils import arggroups, argparse_utils, processes


def parse_args():
    parser = argparse_utils.ArgumentParser(description='Decode I-frame and calculate SHA1.')
    parser.add_argument('--iframes', nargs='*', type=int, default=[1], help='The specific I-frame to decode.')
    arggroups.debug(parser)

    parser.add_argument('path', type=str, help='Path to the video file.')

    args = parser.parse_args()
    arggroups.args_post(args, parser)

    return args

# ffmpeg -nostdin -r 200 -i in.mkv -vf "select='eq(pict_type,I)'" -fps_mode passthrough -an -y out.mp4



def decode_iframes(args):
    return subprocess.Popen(
        (
            'ffmpeg',
            '-nostdin',
            '-i',
            args.path,
            '-an','-fps_mode','passthrough',
            "-vf",
            "select='eq(pict_type,I)'",
            '-vf',
            ','.join(fr'select=eq(n\,{i})' for i in args.iframes),
            '-vframes',
            # '1',
            str(len(args.iframes)),
            '-c:v',
            'rawvideo',
            # '-pixel_format', 'rgb24',
            '-f',
            'image2pipe',
            '-',
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if args.verbose == 0 else None,
    )


def data_sha1(data):
    sha1_hash = hashlib.sha1()
    sha1_hash.update(data)
    return sha1_hash.hexdigest()


def main():
    args = parse_args()
    r = decode_iframes(args)
    stdout, stderr = r.communicate()
    sha1 = data_sha1(stdout)
    print(sha1)


if __name__ == '__main__':
    main()
