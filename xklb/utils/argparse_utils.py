import argparse, sys
from ast import literal_eval

from xklb.utils.iterables import flatten

STDIN_DASH = ["-"]


class ArgparseList(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None) or []

        if isinstance(values, str):
            items.extend(values.split(","))  # type: ignore
        else:
            items.extend(flatten(s.split(",") for s in values))  # type: ignore

        setattr(namespace, self.dest, items)


class ArgparseDict(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        try:
            d = {}
            k_eq_v = list(flatten([val.split(" ") for val in values]))
            for s in k_eq_v:
                k, v = s.split("=", 1)
                if any(sym in v for sym in (" [", " {")):
                    d[k] = literal_eval(v)
                elif v.strip() in ("True", "False"):
                    d[k] = bool(v.strip())
                else:
                    d[k] = v

        except ValueError as ex:
            msg = f'Could not parse argument "{values}" as k1=1 k2=2 format {ex}'
            raise argparse.ArgumentError(self, msg) from ex
        setattr(args, self.dest, d)


class ArgparseArgsOrStdin(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values == STDIN_DASH:
            lines = sys.stdin.readlines()
            if not lines or (len(lines) == 1 and lines[0].strip() == ""):
                lines = None
            else:
                lines = [s.strip() for s in lines]
        else:
            lines = values
        setattr(namespace, self.dest, lines)
