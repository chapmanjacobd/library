import argparse, statistics, typing
from collections import Counter
from typing import Literal

import natsort
import regex as re
from natsort import ns

from xklb import usage
from xklb.utils import arggroups, argparse_utils, consts, iterables, printing, processes
from xklb.utils.log_utils import log
from xklb.utils.objects import Reversor

WordSortOpt = Literal[
    "skip", "len", "count", "dup", "unique", "alpha", "natural", "natsort", "path", "locale", "signed", "os"
]
WORD_SORTS_OPTS = typing.get_args(WordSortOpt)

LineSortOpt = Literal[
    "skip",
    "line",
    "count",
    "len",
    "sum",
    "unique",
    "allunique",
    "alluniques",
    "dup",
    "alldup",
    "alldups",
    "dupmax",
    "dupavg",
    "dupmin",
    "dupmedian",
    "dupmode",
    "alpha",
    "natural",
    "natsort",
    "path",
    "locale",
    "signed",
    "os",
]
LINE_SORTS_OPTS = typing.get_args(LineSortOpt)

REGEXS_DEFAULT = [r"\b\w\w+\b"]
WORD_SORTS_DEFAULT = ["-dup", "count", "-len", "-count", "alpha"]
LINE_SORTS_DEFAULT = ["-allunique", "alpha", "alldup", "dupmode", "line"]


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.regex_sort)
    parser.add_argument("--regexs", "-re", action=argparse_utils.ArgparseList)
    parser.add_argument(
        "--word-sorts",
        "-ws",
        "-wu",
        action=argparse_utils.ArgparseList,
        help=f"""Specify the word sorting strategy to use within each line

Choose ONE OR MORE of the following options:
  skip     skip word sorting
  len      length of word
  unique   word is a unique in corpus (boolean)
  dup      word is a duplicate in corpus (boolean)
  count    count of word in corpus
  alpha    python alphabetic sorting

  natural  natsort default sorting (numbers as integers)
  signed   natsort signed numbers sorting (for negative numbers)
  path     natsort path sorting (https://natsort.readthedocs.io/en/stable/api.html#the-ns-enum)
  locale   natsort system locale sorting
  os       natsort OS File Explorer sorting. To improve non-alphanumeric sorting on Mac OS X and Linux it is necessary to install pyicu (perhaps via python3-icu -- https://gitlab.pyicu.org/main/pyicu#installing-pyicu)

(default: {', '.join(WORD_SORTS_DEFAULT)})""",
    )
    parser.add_argument(
        "--line-sorts",
        "-ls",
        "-lu",
        "-u",
        action=argparse_utils.ArgparseList,
        help=f"""Specify the line sorting strategy to use on the text-processed words (after regex, word-sort, etc)

Choose ONE OR MORE of the following options:
  skip       skip line sorting
  line       the original line (python alphabetic sorting)
  len        length of line
  count      count of words in line

  dup        count of duplicate in corpus words (sum of boolean)
  unique     count of unique in corpus words (sum of boolean)
  alldup     all line-words are duplicate in corpus words (boolean)
  allunique  all line-words are unique in corpus words (boolean)

  sum        count of all uses of line-words (within corpus)
  dupmax     highest line-word corpus usage
  dupmin     lowest line-word corpus usage
  dupavg     average line-word corpus usage
  dupmedian  median line-word corpus usage
  dupmode    mode (most repeated value) line-word corpus usage

  alpha    python alphabetic sorting
  natural  natsort default sorting (numbers as integers)
  ...      the other natsort options specified in --word-sort are also allowed

(default: {', '.join(LINE_SORTS_DEFAULT)})""",
    )
    parser.add_argument("--compat", action="store_true", help="Use natsort compat mode. Treats characters like ⑦ as 7")
    arggroups.cluster(parser)
    arggroups.debug(parser)

    parser.add_argument("input_path", nargs="?", type=argparse.FileType("r"), default="-")
    parser.add_argument("output_path", nargs="?")
    args = parser.parse_args()

    if not args.regexs:
        args.regexs = REGEXS_DEFAULT
    args.regexs = [re.compile(s) for s in args.regexs]

    if not args.word_sorts:
        args.word_sorts = WORD_SORTS_DEFAULT
    if not args.line_sorts:
        args.line_sorts = LINE_SORTS_DEFAULT

    arggroups.args_post(args, parser)

    for option in args.word_sorts:
        if option.lstrip("-") not in WORD_SORTS_OPTS:
            raise ValueError(
                f"--word-sort option '{option}' does not exist. Choose one or more: {', '.join(WORD_SORTS_OPTS)}"
            )

    for option in args.line_sorts:
        if option.lstrip("-") not in LINE_SORTS_OPTS:
            raise ValueError(
                f"--line-sort option '{option}' does not exist. Choose one or more: {', '.join(LINE_SORTS_OPTS)}"
            )

    return args


def line_splitter(regexs: list[re.Pattern], l: str) -> list[str]:
    words = [l]
    for rgx in regexs:
        new_words = []
        for word in words:
            new_words.extend(rgx.findall(word))
        words = new_words
    return words


def word_sorter(NS_OPTS, word_sorts: list[WordSortOpt], corpus_stats: Counter, l: list[str]):
    def generate_custom_key(word):
        key_parts = []
        for s in word_sorts:
            reverse = False
            if s.startswith("-"):
                s = s.lstrip("-")
                reverse = True

            if s == "skip":
                val = None  # no sorting
            elif s == "len":
                val = len(word)
            elif s == "count":
                val = corpus_stats.get(word)
            elif s == "dup":
                val = (corpus_stats.get(word) or 0) > 1
            elif s == "unique":
                val = (corpus_stats.get(word) or 0) == 1

            elif s in ("alpha", "python"):
                val = word
            elif s in ("natural", "natsort"):
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.DEFAULT)(word)
            elif s in ("path", "nspath"):
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.PATH)(word)
            elif s in ("locale", "human"):
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.LOCALE)(word)
            elif s == "signed":
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.REAL)(word)
            elif s == "os":
                val = natsort.os_sort_keygen()(word)
            else:
                raise NotImplementedError

            key_parts.append(Reversor(val) if reverse else val)
        return tuple(key_parts)

    # return list(zip(*[generate_custom_key(xs) for xs in l]))

    for xs in l:
        log.debug("word_sorter xs: %s", generate_custom_key(xs))

    words = sorted(l, key=generate_custom_key)
    log.debug(f"word_sorter: {words}")
    return words


def line_sorter(NS_OPTS, line_sorts: list[LineSortOpt], corpus_stats: Counter, words: list[str], original_line: str):
    def generate_custom_key(words):
        key_parts = []
        for s in line_sorts:
            reverse = False
            if s.startswith("-"):
                s = s.lstrip("-")
                reverse = True

            if s == "skip":
                val = None  # no sorting
            elif s == "line":
                val = original_line
            elif s == "count":
                val = len(words)
            elif s == "len":
                val = len("".join(words))
            elif s == "dup":
                val = sum((corpus_stats.get(word) or 0) > 1 for word in words)
            elif s == "unique":
                val = sum((corpus_stats.get(word) or 0) == 1 for word in words)
            elif s == "alldup":
                val = len(words) >= 1 and all((corpus_stats.get(word) or 0) > 1 for word in words)
            elif s == "allunique":
                val = len(words) >= 1 and all((corpus_stats.get(word) or 0) == 1 for word in words)
            elif s == "alldups":
                val = len(words) > 1 and all((corpus_stats.get(word) or 0) > 1 for word in words)
            elif s == "alluniques":
                val = len(words) > 1 and all((corpus_stats.get(word) or 0) == 1 for word in words)
            elif s == "sum":
                val = sum(corpus_stats.get(word) or 0 for word in words)
            elif s == "dupmax":
                val = max(corpus_stats.get(word) or 0 for word in words)
            elif s == "dupmin":
                val = min(corpus_stats.get(word) or 0 for word in words)
            elif s in ("dupavg", "dupmean"):
                val = statistics.mean(corpus_stats.get(word) or 0 for word in words)
            elif s == "dupmedian":
                try:
                    val = statistics.median(corpus_stats.get(word) or 0 for word in words)
                except statistics.StatisticsError:
                    val = None
            elif s == "dupmode":
                try:
                    val = statistics.mode(corpus_stats.get(word) or 0 for word in words)
                except statistics.StatisticsError:
                    val = None

            elif s in ("alpha", "python"):
                val = words
            elif s in ("natural", "natsort"):
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.DEFAULT)(words)
            elif s in ("path", "nspath"):
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.PATH)(words)
            elif s in ("locale", "human"):
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.LOCALE)(words)
            elif s == "signed":
                val = natsort.natsort_keygen(alg=NS_OPTS | ns.REAL)(words)
            elif s == "os":
                val = natsort.os_sort_keygen()(words)
            else:
                raise NotImplementedError

            key_parts.append(Reversor(val) if reverse else val)
        return tuple(key_parts)

    return generate_custom_key(words)


def prepare_corpus(corpus):
    words = list(iterables.flatten(corpus))
    if len(words) == 0:
        processes.exit_error("no words found. Check your regex! (and remove --duplicates --unique)")

    corpus_stats = Counter(words)
    return words, corpus_stats


def filter_corpus(corpus_stats, words, unique, dups):
    if len(words) == 0:
        return False
    elif unique is True and dups is None:  # --unique
        return any((corpus_stats.get(word) or 0) == 1 for word in words)
    elif unique is False and dups is None:  # --no-unique
        return not any((corpus_stats.get(word) or 0) == 1 for word in words)
    elif unique is True and dups is False:  # --unique --no-dups
        return all((corpus_stats.get(word) or 0) == 1 for word in words)
    elif unique is None and dups is True:  # --dups
        return any((corpus_stats.get(word) or 0) > 1 for word in words)
    elif unique is None and dups is False:  # --no-dups
        return not any((corpus_stats.get(word) or 0) > 1 for word in words)
    elif unique is False and dups is True:  # --no-unique --dups
        return all((corpus_stats.get(word) or 0) > 1 for word in words)
    elif unique is None and dups is None:  # no filtering
        return True
    elif unique is True and dups is True:  # no filtering
        return True
    elif unique is False and dups is False:  # no filtering
        return True
    raise NotImplementedError


def text_processor(args, lines):
    if args.stop_words is None:
        from xklb.data import wordbank

        stop_words = wordbank.stop_words
    else:
        stop_words = set(args.stop_words)

    NS_OPTS = ns.NUMAFTER | ns.NOEXP | ns.NANLAST
    if args.compat:
        NS_OPTS = NS_OPTS | ns.COMPATIBILITYNORMALIZE | ns.GROUPLETTERS

    corpus = []
    for l in lines:
        words = line_splitter(args.regexs, l)
        log.debug(f"line_splitter:    {words}")

        words = [s.lower() for s in words]
        words = [s for s in words if s not in stop_words]
        log.debug(f"stop_word_filter: {words}")

        corpus.append(words)
    words, corpus_stats = prepare_corpus(corpus)

    if args.unique is not None or args.duplicates is not None:
        filtered_indices = [
            i for i, words in enumerate(corpus) if filter_corpus(corpus_stats, words, args.unique, args.duplicates)
        ]
        lines = [lines[i] for i in filtered_indices]
        corpus = [corpus[i] for i in filtered_indices]
        words, corpus_stats = prepare_corpus(corpus)

    avg_word_len = sum(len(word) for word in words) / len(words) if words else 0
    max_word_len = max(len(word) for word in words) if words else 0
    min_word_len = min(len(word) for word in words) if words else 0

    log.info(f"Corpus stats: {min_word_len=} {avg_word_len=:.2f} {max_word_len=}")

    dup_words = set(word for word, count in corpus_stats.items() if count > 1)
    unique_words = set(word for word, count in corpus_stats.items() if count == 1)

    avg_dup_count_per_word = len(dup_words) / len(words)
    avg_dup_count_per_line = len(dup_words) / len(lines)
    avg_unique_count_per_word = len(unique_words) / len(words)
    avg_unique_count_per_line = len(unique_words) / len(lines)
    log.info(f"              {avg_dup_count_per_word=:.2f} {avg_dup_count_per_line=:.2f}")
    log.info(f"              {avg_unique_count_per_word=:.2f} {avg_unique_count_per_line=:.2f}")

    corpus = [word_sorter(NS_OPTS, args.word_sorts, corpus_stats, l) for l in corpus]

    # get original lines but sorted
    line_sort_key = (
        line_sorter(NS_OPTS, args.line_sorts, corpus_stats, words, line)
        for line, words in zip(lines, corpus, strict=True)
    )
    sorted_z = sorted(zip(lines, corpus, line_sort_key, strict=True), key=lambda y: y[2])
    if args.verbose >= consts.LOG_INFO:
        lines = [repr(x[2]) + "\t" + repr(x[1]) + "  # " + x[0] for x in sorted_z]
    else:
        lines = [x[0] for x in sorted_z]
    return lines


def regex_sort() -> None:
    args = parse_args()

    lines = args.input_path.readlines()
    args.input_path.close()

    lines = list(s.rstrip("\n") for s in lines if s.strip())
    lines = text_processor(args, lines)
    lines = (p + "\n" for p in lines)
    if args.output_path:
        with open(args.output_path, "w") as output_fd:
            output_fd.writelines(lines)
    else:
        printing.pipe_lines(lines)


if __name__ == "__main__":
    regex_sort()
