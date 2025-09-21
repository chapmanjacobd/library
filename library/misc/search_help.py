import argparse

from library import __main__, usage
from library.utils import arggroups, argparse_utils, processes


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.search_help)
    arggroups.debug(parser)

    parser.add_argument(
        "subcommand_or_text",
        nargs="+",
        type=str.lower,
        help="The term to search for in command names, descriptions, or help text.",
    )
    args = parser.parse_args()

    arggroups.args_post(args, parser)
    return args


def c(s):
    return s.lower().replace("-", "").replace("_", "")


def args_help(subcommand, text):
    args_usage = processes.cmd("lb", subcommand, "--help").stdout
    if text:
        for l in args_usage.splitlines():
            for t in text:
                if t in l.lower():
                    print(l)
    else:
        print(args_usage)


def search_help():
    args = parse_args()

    all_commands = {
        s.replace("_", "-"): getattr(usage, s)
        for s in dir(usage)
        if not s.startswith("_") and isinstance(getattr(usage, s), str)
    }

    text = args.subcommand_or_text
    subcommand = None
    if text[0].replace("_", "-") in all_commands.keys():
        subcommand, text = text[0].replace("_", "-"), text[1:]

    if subcommand:  # Search within a specific subcommand's help text
        args_help(subcommand, text)
        return

    for category, commands in __main__.progs.items():
        matching_commands = []
        for prog, description in commands.items():
            prog = prog.replace("_", "-")
            prog_usage = getattr(usage, prog.replace("-", "_"), "")
            if any(c(t) in c(prog) or t in description.lower() or t in prog_usage.lower() for t in text):
                matching_commands.append((prog, description, prog_usage))

        print_category = any(t in category.lower() for t in text)
        for prog, description, prog_usage in matching_commands:
            print_prog = any(c(t) in c(prog) or t in description.lower() for t in text)

            symbol = prog[0]
            size = 100
            print(symbol * size)
            txt = f"{description} with lb {prog}"
            print(symbol * 3 + " " + f"{txt + ' ':{symbol}<{size-4}}")
            print(symbol * size)
            print()

            if print_category or print_prog:
                print(prog_usage)
            else:
                args_help(prog, text)

            print()
            print(symbol * size)
            print()
