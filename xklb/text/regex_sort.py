import argparse, statistics
from collections import Counter

import natsort
import regex as re
from natsort import ns

from xklb import usage
from xklb.utils import arggroups, argparse_utils, consts, db_utils, iterables, printing, processes, strings
from xklb.utils.log_utils import log
from xklb.utils.objects import Reversor


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.regex_sort)
    arggroups.text_filtering(parser)
    arggroups.regex_sort(parser)
    arggroups.debug(parser)

    parser.add_argument("input_path", nargs="?", type=argparse.FileType("r"), default="-")
    parser.add_argument("output_path", nargs="?")
    args = parser.parse_args()

    arggroups.regex_sort_post(args)
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


def word_sorter(NS_OPTS, word_sorts: list[consts.WordSortOpt], corpus_stats: Counter, l: list[str]):
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


def line_sorter(
    NS_OPTS, line_sorts: list[consts.LineSortOpt], corpus_stats: Counter, words: list[str], original_line: str
):
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
        log.info([repr(x[2]) + "\t" + repr(x[1]) + "  # " + x[0] for x in sorted_z])

    lines = [x[0] for x in sorted_z]
    return lines


def sort_dicts(args, media):
    search_columns = {
        col
        for _table, table_config in db_utils.config.items()
        if "search_columns" in table_config
        for col in table_config["search_columns"]
    }

    sentence_strings = list(
        strings.path_to_sentence(" ".join(str(v) for k, v in d.items() if v and k in search_columns)) for d in media
    )
    media_keyed = {line: d for line, d in zip(sentence_strings, media, strict=True)}

    lines = text_processor(args, sentence_strings)

    media = [media_keyed[p] for p in lines]
    return media


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
