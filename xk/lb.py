import argparse

from xk.actions import lt, wt


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers()
listen = subparsers.add_parser('listen', aliases=['lt'])
listen.set_defaults(func=lt)

watch = subparsers.add_parser('watch', aliases=['wt'])
watch.set_defaults(func=wt)

parser.parse_known_args(['watch','test'])
parser.parse_known_args(['listen','-p'])
