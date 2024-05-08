import argparse, sys
from ast import literal_eval

from xklb.utils.iterables import flatten
from xklb.utils.strings import format_two_columns

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
            prog = " ".join((parser.usage or "").split(" ", maxsplit=3)[0:2])
            print(f"{prog}: Reading from stdin...", file=sys.stderr)
            lines = sys.stdin.readlines()
            if not lines or (len(lines) == 1 and lines[0].strip() == ""):
                lines = None
            else:
                lines = [s.strip() for s in lines]
        else:
            lines = values
        setattr(namespace, self.dest, lines)


class CustomHelpFormatter(argparse.HelpFormatter):
    def _format_action(self, action):
        help_text = self._expand_help(action) if action.help else ""

        if help_text == "show this help message and exit":
            return ""  # not very useful self-referential humor

        subactions = []
        for subaction in self._iter_indented_subactions(action):
            subactions.append(self._format_action(subaction))

        opts = action.option_strings
        if not opts and not help_text:
            return ""
        elif not opts:  # positional with help text
            opts = [action.dest.upper()]

        if len(opts) == 1:
            left = opts[0]
        elif opts[1].startswith("--no-"):  #  argparse.BooleanOptionalAction
            left = f"{opts[0]} / {opts[1]}"
        elif opts[-1].startswith("--"):
            left = opts[0]
        else:
            left = f"{opts[0]} ({opts[-1]})"

        left += " " + self._format_args(action, "VALUE") + "\n"

        return "".join(subactions) + format_two_columns(left, help_text)


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["formatter_class"] = lambda prog: CustomHelpFormatter(prog, max_help_position=40)
        super().__init__(*args, **kwargs)


def suppress_destinations(parser, destinations):
    for action in parser._actions:
        if action.dest in destinations:
            action.help = argparse.SUPPRESS


def arggroup_destinations(functions):
    temp_parser = ArgumentParser(add_help=False)
    for func in functions:
        func(temp_parser)
    return set(o.dest for o in temp_parser._actions)


def suppress_arggroups(parser, functions):
    destinations = arggroup_destinations(functions)
    suppress_destinations(parser, destinations)
