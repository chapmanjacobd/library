import argparse, sys

from library import __main__
from library.utils import arggroups, argparse_utils, processes


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=__main__.command_usage("search-help"))
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
    args_usage = processes.cmd(sys.executable, "-m", "library", *subcommand.split(), "--help").stdout
    if text:
        for l in args_usage.splitlines():
            for t in text:
                if t in l.lower():
                    print(l)
    else:
        print(args_usage)


def search_help():
    args = parse_args()

    target_paths = __main__.canonical_target_paths()
    alias_targets = __main__.module_alias_targets()
    all_commands = {
        command: target_paths[target]
        for command, target in alias_targets.items()
        if target in target_paths
    }
    all_commands.update({path: path for path in target_paths.values()})

    text = args.subcommand_or_text
    subcommand = None
    for end in range(len(text), 0, -1):
        candidate = " ".join(text[:end]).replace("_", "-")
        nested_target = __main__.nested_target(text[:end])
        if candidate in all_commands:
            subcommand, text = all_commands[candidate], text[end:]
            break
        if nested_target is not None and nested_target[1] == end:
            subcommand, text = target_paths[nested_target[0]], text[end:]
            break

    if subcommand:  # Search within a specific subcommand's help text
        args_help(subcommand, text)
        return

    for category, commands in __main__.command_catalog():
        matching_commands = []
        for canonical_path, description in commands:
            prog_usage = __main__.canonicalize_usage_for_command(
                __main__.command_usage(canonical_path),
                canonical_path,
            )
            if any(
                c(t) in c(canonical_path)
                or t in description.lower()
                or t in prog_usage.lower()
                for t in text
            ):
                matching_commands.append((canonical_path, description, prog_usage))

        print_category = any(t in category.lower() for t in text)
        for canonical_path, description, prog_usage in matching_commands:
            print_prog = any(
                c(t) in c(canonical_path)
                or t in description.lower()
                for t in text
            )

            symbol = canonical_path[0]
            size = 100
            print(symbol * size)
            txt = f"{description} with lb {canonical_path}"
            print(symbol * 3 + " " + f"{txt + ' ':{symbol}<{size - 4}}")
            print(symbol * size)
            print()

            if print_category or print_prog:
                print(prog_usage)
            else:
                args_help(canonical_path, text)

            print()
            print(symbol * size)
            print()
