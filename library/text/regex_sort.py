import argparse, statistics
from collections import Counter
from functools import partial

import natsort
import regex as re
from natsort import ns

from library import usage
from library.table import mcda
from library.utils import arggroups, argparse_utils, consts, db_utils, iterables, printing, processes, strings
from library.utils.log_utils import log
from library.utils.objects import Reverser


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.regex_sort)
    arggroups.text_filtering(parser)
    arggroups.regex_sort(parser)
    arggroups.debug(parser)

    parser.add_argument("input_path", nargs="?", default="-")
    parser.add_argument("output_path", nargs="?")
    args = parser.parse_args()
    args.input_path = argparse_utils.open_text_input(parser, args.input_path)

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


def _word_sort_value(sort_name, word, corpus_stats, words, reverse_words, ns_opts):
    sort_values = {
        "skip": lambda: None,
        "len": lambda: len(word),
        "count": lambda: corpus_stats.get(word),
        "dup": lambda: (corpus_stats.get(word) or 0) > 1,
        "unique": lambda: (corpus_stats.get(word) or 0) == 1,
        "index": lambda: words.index(word),
        "lastindex": lambda: reverse_words.index(word),
        "linecount": lambda: words.count(word),
        "alpha": lambda: word,
        "python": lambda: word,
        "natural": lambda: natsort.natsort_keygen(alg=ns_opts | ns.DEFAULT)(word),
        "natsort": lambda: natsort.natsort_keygen(alg=ns_opts | ns.DEFAULT)(word),
        "path": lambda: natsort.natsort_keygen(alg=ns_opts | ns.PATH)(word),
        "nspath": lambda: natsort.natsort_keygen(alg=ns_opts | ns.PATH)(word),
        "locale": lambda: natsort.natsort_keygen(alg=ns_opts | ns.LOCALE)(word),
        "human": lambda: natsort.natsort_keygen(alg=ns_opts | ns.LOCALE)(word),
        "signed": lambda: natsort.natsort_keygen(alg=ns_opts | ns.REAL)(word),
        "os": lambda: natsort.os_sort_keygen()(word),
    }
    try:
        return sort_values[sort_name]()
    except KeyError as exc:
        raise NotImplementedError from exc


def _gen_word_key(word_sorts, word, ns_opts, corpus_stats, words, reverse_words):
    key_parts = []
    for sort_option in word_sorts:
        reverse = sort_option.startswith("-")
        sort_name = sort_option.lstrip("-") if reverse else sort_option
        value = _word_sort_value(sort_name, word, corpus_stats, words, reverse_words, ns_opts)
        key_parts.append(Reverser(value) if reverse else value)
    log.debug("word_sorter xs: %s", key_parts)
    return tuple(key_parts)


def word_sorter(args, ns_opts, word_sorts: list[consts.WordSortOpt], corpus_stats: Counter, l: list[str]):
    reverse_words = list(reversed(l))

    try:
        split_index = word_sorts.index("mcda")
    except ValueError:
        words = sorted(l, key=partial(_gen_word_key, word_sorts, ns_opts=ns_opts, corpus_stats=corpus_stats, words=l, reverse_words=reverse_words))
    else:
        # Split the list into two parts
        before_mcda = word_sorts[:split_index]
        after_mcda = word_sorts[split_index + 1 :]  # remove "mcda" from word_sorts

        rank = mcda.mcda_sorted(
            args,
            keys=[
                _gen_word_key(after_mcda, xs, ns_opts, corpus_stats, l, reverse_words)
                for xs in l
            ],
        )
        log.debug("word_sorter mcda: %s", [l[i] for i in rank["original_index"]])
        words = sorted(
            l,
            key=lambda word: (
                *_gen_word_key(before_mcda, word, ns_opts, corpus_stats, l, reverse_words),
                rank["original_index"][l.index(word)],
            ),
        )

    log.debug(f"word_sorter: {words}")
    return words


def line_sorter(
    args,
    ns_opts,
    line_sorts: list[consts.LineSortOpt],
    corpus_stats: Counter,
    original_lines: list[str],
    corpus: list[list[str]],
):
    try:
        split_index = line_sorts.index("mcda")
    except ValueError:
        before_mcda = line_sorts
        after_mcda = []
    else:
        before_mcda = line_sorts[:split_index]
        after_mcda = line_sorts[split_index + 1 :]  # remove "mcda" from line_sorts

    mcda_index = None
    if after_mcda:
        keys = [
            _gen_line_key(after_mcda, original_line, words, corpus_stats, ns_opts)
            for words, original_line in zip(corpus, original_lines, strict=True)
        ]
        rank = mcda.mcda_sorted(args, keys)
        mcda_index = rank["original_index"]

    line_sort_keys: list[tuple[tuple, str]] = []
    for line_idx, (words, original_line) in enumerate(zip(corpus, original_lines, strict=True)):
        line_sort_key = _gen_line_key(before_mcda, original_line, words, corpus_stats, ns_opts)
        if mcda_index is not None:
            line_sort_key += (mcda_index[line_idx],)
        log.debug(repr(line_sort_key) + "\t" + repr(words))
        line_sort_keys.append((line_sort_key, original_line))

    sorted_z = sorted(line_sort_keys, key=lambda y: y[0])
    lines = [x[1] for x in sorted_z]
    return lines


def _safe_line_statistic(function, values):
    try:
        return function(values)
    except statistics.StatisticsError:
        return None


def _line_sort_value(sort_name, original_line, words, corpus_stats, ns_opts):
    duplicate_counts = [corpus_stats.get(word) or 0 for word in words]
    value_functions = {
        "skip": lambda: None,
        "line": lambda: original_line,
        "count": lambda: len(words),
        "len": lambda: len("".join(words)),
        "dup": lambda: sum(count > 1 for count in duplicate_counts),
        "unique": lambda: sum(count == 1 for count in duplicate_counts),
        "alldup": lambda: len(words) >= 1 and all(count > 1 for count in duplicate_counts),
        "allunique": lambda: len(words) >= 1 and all(count == 1 for count in duplicate_counts),
        "alldups": lambda: len(words) > 1 and all(count > 1 for count in duplicate_counts),
        "alluniques": lambda: len(words) > 1 and all(count == 1 for count in duplicate_counts),
        "sum": lambda: sum(duplicate_counts),
        "dupmax": lambda: max(duplicate_counts, default=None),
        "dupmin": lambda: min(duplicate_counts, default=None),
        "dupavg": lambda: statistics.mean(duplicate_counts),
        "dupmean": lambda: statistics.mean(duplicate_counts),
        "dupmedian": lambda: _safe_line_statistic(statistics.median, duplicate_counts),
        "dupmode": lambda: _safe_line_statistic(statistics.mode, duplicate_counts),
        "alpha": lambda: words,
        "python": lambda: words,
        "natural": lambda: natsort.natsort_keygen(alg=ns_opts | ns.DEFAULT)(words),
        "natsort": lambda: natsort.natsort_keygen(alg=ns_opts | ns.DEFAULT)(words),
        "path": lambda: natsort.natsort_keygen(alg=ns_opts | ns.PATH)(words),
        "nspath": lambda: natsort.natsort_keygen(alg=ns_opts | ns.PATH)(words),
        "locale": lambda: natsort.natsort_keygen(alg=ns_opts | ns.LOCALE)(words),
        "human": lambda: natsort.natsort_keygen(alg=ns_opts | ns.LOCALE)(words),
        "signed": lambda: natsort.natsort_keygen(alg=ns_opts | ns.REAL)(words),
        "os": lambda: natsort.os_sort_keygen()(words),
    }
    try:
        return value_functions[sort_name]()
    except KeyError as exc:
        raise NotImplementedError from exc


def _gen_line_key(line_sorts, original_line, words, corpus_stats, ns_opts):
    key_parts = []
    for sort_option in line_sorts:
        reverse = sort_option.startswith("-")
        sort_name = sort_option.lstrip("-") if reverse else sort_option
        value = _line_sort_value(sort_name, original_line, words, corpus_stats, ns_opts)
        key_parts.append(Reverser(value) if reverse else value)
    return tuple(key_parts)


def prepare_corpus(corpus):
    words = list(iterables.flatten(corpus))
    if len(words) == 0:
        processes.exit_error("no words found. Check your regex! (and remove --duplicates --unique)")

    corpus_stats = Counter(words)
    return words, corpus_stats


def filter_corpus(corpus_stats, words, unique, dups):
    if len(words) == 0:
        return False

    def unique_count():
        return any((corpus_stats.get(word) or 0) == 1 for word in words)

    def duplicate_count():
        return any((corpus_stats.get(word) or 0) > 1 for word in words)
    rules = {
        (True, None): unique_count,
        (False, None): lambda: not unique_count(),
        (True, False): lambda: all((corpus_stats.get(word) or 0) == 1 for word in words),
        (None, True): duplicate_count,
        (None, False): lambda: not duplicate_count(),
        (False, True): lambda: all((corpus_stats.get(word) or 0) > 1 for word in words),
        (None, None): lambda: True,
        (True, True): lambda: True,
        (False, False): lambda: True,
    }
    try:
        return rules[unique, dups]()
    except KeyError as exc:
        raise NotImplementedError from exc


def text_processor(args, lines):
    if not lines:
        processes.no_media_found()

    if getattr(args, "stop_words", None) is None:
        from library.data import wordbank

        stop_words = wordbank.stop_words
    else:
        stop_words = set(args.stop_words)

    ns_opts = ns.NUMAFTER | ns.NOEXP | ns.NANLAST
    if args.compat:
        ns_opts = ns_opts | ns.COMPATIBILITYNORMALIZE | ns.GROUPLETTERS

    corpus = []
    for raw_line in lines:
        line = raw_line.replace("http://", "", 1)
        line = line.replace("https://", "", 1)

        words = line_splitter(args.regexs, line)
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

    corpus = [word_sorter(args, ns_opts, args.word_sorts, corpus_stats, l) for l in corpus]

    # get original lines but sorted
    lines = line_sorter(args, ns_opts, args.line_sorts, corpus_stats, lines, corpus)
    return lines


def sort_dicts(args, media, search_columns=None):
    if search_columns is None:
        search_columns = {
            col
            for _table, table_config in db_utils.config.items()
            if "search_columns" in table_config
            for col in table_config["search_columns"]
        }

    sentence_strings = list(
        strings.path_to_sentence(" ".join(str(v) for k, v in d.items() if v and k in search_columns)) for d in media
    )
    media_keyed = dict(zip(sentence_strings, media, strict=True))

    lines = text_processor(args, sentence_strings)

    media = [media_keyed[p] for p in lines]
    return media


def regex_sort() -> None:
    args = parse_args()

    lines = args.input_path.readlines()
    args.input_path.close()

    lines = list(s.rstrip("\n") for s in lines if s.strip())

    if args.preprocess:
        sentence_strings = [strings.path_to_sentence(s) for s in lines]
        lines_keyed = dict(zip(sentence_strings, lines, strict=True))
        sorted_sentence_strings = text_processor(args, sentence_strings)
        lines = [lines_keyed[p] + "\n" for p in sorted_sentence_strings]
    else:
        lines = text_processor(args, lines)
        lines = (p + "\n" for p in lines)

    if args.output_path:
        with open(args.output_path, "w") as output_fd:
            output_fd.writelines(lines)
    else:
        printing.pipe_lines(lines)
