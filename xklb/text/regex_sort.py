import argparse
from collections import Counter

import regex as re
from natsort import natsort_keygen

from xklb import usage
from xklb.utils import arggroups, argparse_utils, consts, iterables, printing
from xklb.utils.log_utils import log

natsort_key = natsort_keygen()


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.regex_sort)
    parser.add_argument("--regexs", "-re", action=argparse_utils.ArgparseList)
    parser.add_argument("--word-sorts", action=argparse_utils.ArgparseList)
    parser.add_argument("--line-sorts", action=argparse_utils.ArgparseList)
    parser.add_argument("--duplicates", "--dups", action="store_true")
    parser.add_argument("--uniques", "-u", action="store_true")
    arggroups.cluster(parser)
    arggroups.debug(parser)

    parser.add_argument("input_path", nargs="?", type=argparse.FileType("r"), default="-")
    parser.add_argument("output_path", nargs="?")
    args = parser.parse_args()

    if not args.regexs:
        args.regexs = [r"\b\w\w+\b"]
    args.regexs = [re.compile(s) for s in args.regexs]

    if not args.word_sorts:
        args.word_sorts = ["dup", "-len", "natsort"]
    if not args.line_sorts:
        args.line_sorts = ["natsort", "dup"]

    arggroups.args_post(args, parser)

    return args


def line_splitter(regexs: list[re.Pattern], l: str) -> list[str]:
    words = [l]
    for rgx in regexs:
        new_words = []
        for word in words:
            new_words.extend(rgx.findall(word))
        words = new_words
    return words


def word_sorter(word_sorts: list[str], unique_words: set, l: list[str]):
    def generate_custom_key(word):
        key_parts = []
        for sort_type in word_sorts:
            if sort_type == "skip":
                key_parts.append(None)  # no sorting
            elif sort_type == "len":
                key_parts.append(len(word))
            elif sort_type == "-len":
                key_parts.append(-len(word))
            elif sort_type == "alpha":
                key_parts.append(word)
            elif sort_type == "natsort":
                key_parts.append(natsort_key(word))
            elif sort_type == "dup":
                key_parts.append(word not in unique_words)
            elif sort_type == "unique":
                key_parts.append(word in unique_words)
            else:
                raise NotImplementedError
        return tuple(key_parts)

    # return list(zip(*[generate_custom_key(xs) for xs in l]))

    for xs in l:
        log.debug("word_sorter xs: %s", generate_custom_key(xs))

    words = sorted(l, key=generate_custom_key)
    log.debug(f"word_sorter: {words}")
    return words


def line_sorter(line_sorts: list[str], unique_words: set, l: list[str]):
    def generate_custom_key(words: list[str]):
        key_parts = []
        for sort_type in line_sorts:
            if sort_type == "skip":
                key_parts.append(None)  # no sorting
            elif sort_type == "len":
                key_parts.append(len(words))
            elif sort_type == "-len":
                key_parts.append(-len(words))
            elif sort_type == "alpha":
                key_parts.append(words)
            elif sort_type == "natsort":
                key_parts.append(natsort_key(words))
            elif sort_type == "dup":
                key_parts.append(len(set(l).difference(unique_words)))
            elif sort_type == "unique":
                key_parts.append(len(set(l).intersection(unique_words)))
            else:
                raise NotImplementedError
        return tuple(key_parts)

    return generate_custom_key(l)


def prepare_corpus(corpus):
    words = list(iterables.flatten(corpus))
    corpus_stats = Counter(words)
    dup_words = set(word for word, count in corpus_stats.items() if count > 1)
    unique_words = set(word for word, count in corpus_stats.items() if count == 1)
    return words, dup_words, unique_words


def text_processor(args, lines):
    if args.stop_words is None:
        from xklb.data import wordbank

        stop_words = wordbank.stop_words
    else:
        stop_words = set(args.stop_words)

    corpus = []
    for l in lines:
        words = line_splitter(args.regexs, l)
        log.debug(f"line_splitter:    {words}")

        words = [s for s in words if s not in stop_words]
        log.debug(f"stop_word_filter: {words}")

        corpus.append(words)
    words, dup_words, unique_words = prepare_corpus(corpus)

    # if args.unique:
    # elif args.duplicates:
    #     new_lines = []
    #     for l in lines:
    #         for w in ...  TODO: implement this
    #     words, dup_words, unique_words = prepare_corpus(corpus)

    avg_word_len = sum(len(word) for word in words) / len(words) if words else 0
    max_word_len = max(len(word) for word in words) if words else 0
    min_word_len = min(len(word) for word in words) if words else 0

    log.info(f"Corpus stats: {min_word_len=} {avg_word_len=:.2f} {max_word_len=}")

    avg_dup_count_per_word = len(dup_words) / len(words)
    avg_dup_count_per_line = len(dup_words) / len(lines)
    avg_unique_count_per_word = len(unique_words) / len(words)
    avg_unique_count_per_line = len(unique_words) / len(lines)
    log.info(f"              {avg_dup_count_per_word=:.2f} {avg_dup_count_per_line=:.2f}")
    log.info(f"              {avg_unique_count_per_word=:.2f} {avg_unique_count_per_line=:.2f}")

    corpus = [word_sorter(args.word_sorts, unique_words, l) for l in corpus]
    corpus = [line_sorter(args.line_sorts, unique_words, l) for l in corpus]

    # get original lines but sorted
    z = list(zip(lines, corpus, strict=True))
    sorted_z = sorted(z, key=lambda y: y[1])
    if args.verbose >= consts.LOG_INFO:
        lines = [repr(x[1]) + "  # " + x[0] for x in sorted_z]
    else:
        lines = [x[0] for x in sorted_z]
    return lines


def regex_sort() -> None:
    args = parse_args()

    lines = args.input_path.readlines()
    args.input_path.close()

    lines = list(s.rstrip("\n") for s in lines)
    lines = text_processor(args, lines)
    lines = (p + "\n" for p in lines)
    if args.output_path:
        with open(args.output_path, "w") as output_fd:
            output_fd.writelines(lines)
    else:
        printing.pipe_lines(lines)


if __name__ == "__main__":
    regex_sort()
