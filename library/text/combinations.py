import json

from library.utils import arg_utils, arggroups, argparse_utils, objects, printing
from library.utils.log_utils import log

USAGE = {
    'combinations': """library text combinations --PROPERTY OPTION

    Enumerate the possible combinations of things that have multiple properties with more than one options

        library text combinations --prop1 opt1 --prop1 opt2 --prop2 A --prop2 B

        {"prop1": "opt1", "prop2": "A"}
        {"prop1": "opt1", "prop2": "B"}
        {"prop1": "opt2", "prop2": "A"}
        {"prop1": "opt2", "prop2": "B"}
""",
}


def parse_utils():
    parser = argparse_utils.ArgumentParser(usage=USAGE['combinations'])
    arggroups.debug(parser)

    args, unknown_args = parser.parse_known_args()
    arggroups.args_post(args, parser)
    return args, unknown_args


def combinations():
    args, unknown_args = parse_utils()

    data = arg_utils.dict_of_lists_from_unknown_args(unknown_args)
    if not data:
        log.error("No data given via arguments")
        raise SystemExit(2)

    log.info(dict(data))
    for d in objects.product(**data):
        printing.pipe_lines(json.dumps(d) + "\n")
