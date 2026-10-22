from library import usage
from library.document import document_convert


def parse_args():
    return document_convert.build_parser(usage.document_convert)


def text_convert() -> None:
    args = parse_args()
    document_convert.convert_paths(args)
