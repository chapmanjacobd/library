import argparse, sys
from ast import literal_eval

from xklb.utils.iterables import flatten


class ArgparseList(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None) or []

        items.extend(values.split(","))  # type: ignore

        setattr(namespace, self.dest, items)


class ArgparseDict(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        try:
            d = {}
            k_eq_v = list(flatten([val.split(" ") for val in values]))
            for s in k_eq_v:
                k, v = s.split("=")
                if any(sym in v for sym in ("[", "{")):
                    d[k] = literal_eval(v)
                else:
                    d[k] = v

        except ValueError as ex:
            msg = f'Could not parse argument "{values}" as k1=1 k2=2 format {ex}'
            raise argparse.ArgumentError(self, msg) from ex
        setattr(args, self.dest, d)


class ArgparseArgsOrStdin(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values == ["-"]:
            lines = sys.stdin.readlines()
        else:
            lines = values
        setattr(namespace, self.dest, lines)
