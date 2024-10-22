import argparse, json, shlex, sys
from ast import literal_eval

from xklb.utils import nums
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


class ArgparseSlice(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if not isinstance(values, str):
            raise TypeError

        if ":" in values:
            parts = values.split(":")
            if len(parts) > 3:
                raise ValueError

            start = ""
            stop = ""
            step = ""
            if len(parts) >= 1:
                start = parts[0]
            if len(parts) >= 2:
                stop = parts[1]
            if len(parts) == 3:
                step = parts[2]

            slice_obj = slice(int(start) if start else None, int(stop) if stop else None, int(step) if step else None)
        else:
            slice_obj = slice(int(values), None)

        setattr(namespace, self.dest, slice_obj)


class ArgparseDict(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        try:
            d = {}
            k_eq_v = list(values.split(" "))
            for s in k_eq_v:
                k, v = s.split("=", 1)
                v_strip = v.strip()
                if any(sym in v for sym in (" [", " {")):
                    d[k] = literal_eval(v)
                elif v_strip in ("True", "False"):
                    d[k] = bool(v_strip)
                elif v_strip.isnumeric():
                    d[k] = nums.safe_int_float_str(v_strip)
                else:
                    d[k] = v

        except ValueError as ex:
            msg = f'Could not parse argument "{values}" as k1=1 k2=2 format {ex}'
            raise argparse.ArgumentError(self, msg) from ex
        setattr(args, self.dest, d)


class ArgparseArgsOrStdin(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values == STDIN_DASH:
            print(f"{parser.prog}: Reading from stdin...", file=sys.stderr)
            lines = sys.stdin.readlines()
            if not lines or (len(lines) == 1 and lines[0].strip() == ""):
                lines = None
            else:
                lines = [s.strip() for s in lines]
        else:
            lines = values
        setattr(namespace, self.dest, lines)


def is_sqlite(path):
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\000"
    except OSError:
        return False


class ArgparseDBOrPaths(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        database = None
        paths = None
        if values == STDIN_DASH:
            print(f"{parser.prog}: Reading from stdin...", file=sys.stderr)
            paths = sys.stdin.readlines()
            if not paths or (len(paths) == 1 and paths[0].strip() == ""):
                paths = None
            else:
                paths = [s.strip() for s in paths]
        elif values is not None and len(values) == 1 and is_sqlite(values[0]):
            database = values[0]
            paths = None
        else:
            paths = values
        setattr(namespace, "database", database)
        setattr(namespace, self.dest, paths)


def type_to_str(t):
    type_dict = {
        int: "Integer",
        float: "Float",
        bool: "Boolean",
        str: "String",
        list: "List",
        tuple: "Tuple",
        dict: "Dictionary",
        set: "Set",
    }
    _type = type_dict.get(t)

    if _type is None and getattr(t, "__annotations__", False):
        _type = type_dict.get(t.__annotations__["return"])
    if _type is None:
        _type = "Value"

    return _type.upper()


def default_to_str(obj):
    if obj is None:
        return None
    elif isinstance(obj, (list, tuple, set)):
        if len(obj) == 0:
            return None
        else:
            return '"' + ", ".join(shlex.quote(s) for s in obj) + '"'
    elif isinstance(obj, dict):
        return json.dumps(obj)
    if isinstance(obj, str):
        return '"' + str(obj) + '"'
    else:
        return str(obj)


class CustomHelpFormatter(argparse.RawTextHelpFormatter):
    def _metavar_formatter(self, action, default_metavar):
        if action.metavar is not None:
            result = action.metavar
        elif action.choices is not None:
            choice_strs = [str(choice) for choice in action.choices]
            result = "{%s}" % " ".join(choice_strs)
        else:
            result = default_metavar

        def format(tuple_size):  # noqa: A001
            if isinstance(result, tuple):
                return result
            else:
                return (result,) * tuple_size

        return format

    def _format_args(self, action, default_metavar):
        get_metavar = self._metavar_formatter(action, default_metavar)
        if action.nargs == argparse.ZERO_OR_MORE:
            result = "[%s ...]" % get_metavar(1)
        elif action.nargs == argparse.ONE_OR_MORE:
            result = "%s ..." % get_metavar(1)
        else:
            result = super()._format_args(action, default_metavar)
        return result

    def _format_default(self, action, opts):
        default = ""
        if action.default is not None:
            if isinstance(action, argparse.BooleanOptionalAction):
                if action.default:
                    default = opts[0]
                else:
                    default = opts[1]
            elif isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                pass
            elif action.default == "":
                pass
            else:
                default = default_to_str(action.default)
        return default

    def _format_usage(self, usage, actions, groups, prefix):
        if usage is None:
            return super()._format_usage(usage, actions, groups, prefix)

        return "usage: %s\n\n" % usage

    def _format_action(self, action):
        help_text = self._expand_help(action) if action.help else ""

        if help_text == "show this help message and exit":
            return ""  # not very useful self-referential humor

        subactions = [self._format_action(subaction) for subaction in self._iter_indented_subactions(action)]

        opts = action.option_strings
        if not opts and not help_text:
            return ""
        elif not opts:  # positional with help text
            opts = [action.dest.upper()]

        if len(opts) == 1:
            left = opts[0]
        elif isinstance(action, argparse.BooleanOptionalAction):
            left = f"{opts[0]} / {opts[1]}"
        elif opts[-1].startswith("--"):
            left = opts[0]
        else:
            left = f"{opts[0]} ({opts[-1]})"

        left += "\n  " + self._format_args(action, type_to_str(action.type or str))
        left += "\n"

        default = self._format_default(action, opts)
        const = default_to_str(action.const)

        extra = []
        if default:
            extra.append(f"default: {default}")
        if not isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)) and const:
            extra.append(f"const: {const}")
        extra = "; ".join(extra)

        extra = extra.rstrip()
        if extra:
            help_text = help_text or ""
            if help_text:
                help_text += " "
            help_text += f"({extra})"

        return "".join(subactions) + format_two_columns(left, help_text)


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["prog"] = " ".join((kwargs.get("usage") or "").split(" ", maxsplit=3)[0:2]).strip() or None
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
