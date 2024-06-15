import argparse, json, shlex, sys
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
            print(f"{parser.prog}: Reading from stdin...", file=sys.stderr)
            lines = sys.stdin.readlines()
            if not lines or (len(lines) == 1 and lines[0].strip() == ""):
                lines = None
            else:
                lines = [s.strip() for s in lines]
        else:
            lines = values
        setattr(namespace, self.dest, lines)


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

        def format(tuple_size):
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
