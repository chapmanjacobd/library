import json, sys

from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils, printing, processes, strings
from xklb.utils.log_utils import log


def parse_utils():
    parser = argparse_utils.ArgumentParser(usage=usage.json_keys_rename)
    arggroups.debug(parser)

    args, unknown_args = parser.parse_known_args()
    arggroups.args_post(args, parser)
    return args, unknown_args


def rename_keys(json_data, key_mapping):
    key_mapping = {old_key: new_key for new_key, old_key in key_mapping.items()}  # swap keys
    keys_to_rename = list(key_mapping.keys())

    new_data = {}
    for key_to_rename in keys_to_rename:
        for old_key in list(json_data.keys()):
            if key_to_rename in old_key.lower():
                new_key = key_mapping[key_to_rename]
                new_data[new_key] = json_data.pop(old_key)
                break

    return new_data


def gen_d(line):
    json_data = strings.safe_json_loads(line)
    if isinstance(json_data, list):
        yield from json_data
    elif isinstance(json_data, dict):
        yield json_data
    else:
        raise TypeError


def json_keys_rename():
    args, unknown_args = parse_utils()

    key_mapping = arg_utils.dict_from_unknown_args(unknown_args)
    if not key_mapping:
        log.error("No data given via arguments")
        raise SystemExit(2)

    print("json-keys-rename: Reading from stdin...", file=sys.stderr)
    lines = sys.stdin.readlines()
    if not lines or (len(lines) == 1 and lines[0].strip() == ""):
        processes.exit_error("No data passed in")
    else:
        lines = [s.strip() for s in lines]

    for l in lines:
        for d in gen_d(l):
            renamed_data = rename_keys(d, key_mapping)
            printing.pipe_lines(json.dumps(renamed_data) + "\n")
