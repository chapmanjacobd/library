import argparse
from pathlib import Path

from xklb import usage
from xklb.utils import arg_utils, file_utils, iterables, objects, sql_utils
from xklb.utils.consts import DEFAULT_FILE_ROWS_READ_LIMIT
from xklb.utils.log_utils import log
from xklb.utils.printing import print_df, print_series


def parse_args():
    parser = argparse.ArgumentParser(description="Perform MCDA on one or more files", usage=usage.mcda)
    parser.add_argument("--mimetype", "--filetype")
    parser.add_argument("--encoding")
    parser.add_argument("--table-name", "--table", "-t")
    parser.add_argument("--table-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--end-row", "--nrows", "--limit", "-L", default=str(DEFAULT_FILE_ROWS_READ_LIMIT))
    parser.add_argument(
        "--minimize-columns",
        "--minimize-cols",
        "--minimize",
        "--min",
        nargs="*",
        action=arg_utils.ArgparseList,
        default=[],
    )
    parser.add_argument(
        "--columns-exclude",
        "--exclude-columns",
        "--ignore-columns",
        nargs="*",
        action=arg_utils.ArgparseList,
        default=[],
    )
    parser.add_argument(
        "--columns-include",
        "--include-columns",
        "--columns",
        "--cols",
        nargs="*",
        action=arg_utils.ArgparseList,
        default=[],
    )
    parser.add_argument("--words-nums-map")
    parser.add_argument("--mcda-method")
    parser.add_argument("--nodata", type=int, default=0)
    parser.add_argument("--sort", "-u", default="random()")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument(
        "paths",
        metavar="path",
        nargs="+",
        help="path to one or more files",
    )
    args = parser.parse_args()

    if args.end_row.lower() in ("inf", "none", "all"):
        args.end_row = None
    else:
        args.end_row = int(args.end_row)

    if args.words_nums_map:
        Path(args.words_nums_map).touch()

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def words_to_numbers(args, words):
    default = {
        "high": 5,
        "above average": 4,
        "average": 3,
        "below average": 2,
        "low": 1,
    }

    numbers = []
    with objects.json_shelve(args.words_nums_map, default) as mappings:
        for word in words:
            word = word.lower()

            try:
                number = mappings[word]
            except KeyError:  # word not in mappings
                number = int(input(f"Enter a number for '{word}': "))
                mappings[word] = number  # save it for the future

            numbers.append(number)

    return numbers


def borda(df, weights):
    import numpy as np

    m, n = df.shape
    matrix = np.array(df)
    borda_matrix = np.empty((m, n))
    for i in range(n):
        borda_matrix[:, i] = m - matrix[:, i]
    w_borda_matrix = borda_matrix * weights

    borda_points = np.sum(w_borda_matrix, axis=1)
    return borda_points


def auto_mcda(args, df, alternatives, minimize_cols):
    import numpy as np
    import pandas as pd
    from pymcdm import weights as w
    from pymcdm.methods import MABAC, SPOTIS, TOPSIS

    goal_directions = np.array([-1 if col in minimize_cols else 1 for col in alternatives.columns])
    alternatives_np = alternatives.fillna(getattr(args, "nodata", 0)).to_numpy()
    methods = [TOPSIS(), MABAC(), SPOTIS(SPOTIS.make_bounds(alternatives_np))]
    method_names = ["TOPSIS", "MABAC", "SPOTIS"]
    votes = []
    for method in methods:
        # TODO: --weights flag to override
        weights = w.entropy_weights(alternatives_np)
        pref = method(alternatives_np, weights, goal_directions)
        votes.append(pref)
    votes_df = pd.DataFrame(zip(*votes), columns=method_names)
    borda_points = borda(votes_df, weights=[1] * len(votes))
    borda_df = pd.DataFrame({"BORDA": borda_points}, index=df.index)

    # TODO: warning if a criterion accounts for less than 3% of variance (PCA)

    df = pd.concat((df, votes_df, borda_df), axis=1).sort_values(
        getattr(args, "mcda_method", "TOPSIS"), ascending=False
    )
    return df


def sort(args, df, values):
    columns = []
    if isinstance(values, str):
        columns.extend(values.split(","))
    else:
        columns.extend(iterables.flatten(s.split(",") for s in values))

    if columns:
        included_columns = [s.lstrip("-") for s in columns]
        alternatives = df[included_columns]
    else:
        alternatives = df.select_dtypes("number")

    df = auto_mcda(args, df, alternatives, minimize_cols=set(s.lstrip("-") for s in columns if s.startswith("-")))
    return df


def group_sort_by(args, folders):
    if args.sort_by.startswith("mcda "):
        import pandas as pd

        if not isinstance(folders, pd.DataFrame):
            folders = pd.DataFrame(folders)
        values = args.sort_by.replace("mcda ", "", 1)
        df = sort(args, folders, values)
        return df.drop(columns=["TOPSIS", "MABAC", "SPOTIS", "BORDA"]).to_dict(orient="records")
    else:
        sort_func = lambda x: x["size"] / x["exists"]
        if args.sort_by:
            if args.sort_by == "played_ratio":
                sort_func = lambda x: x["played"] / x["deleted"] if x["deleted"] else 0
            elif args.sort_by == "deleted_ratio":
                sort_func = lambda x: x["deleted"] / x["played"] if x["played"] else 0
            else:
                sort_func = sql_utils.sort_like_sql(args.sort_by)

        return sorted(folders, key=sort_func)


def print_info(args, df):
    if df.shape == (0, 0):
        print(f"Table [{df.name}] empty")
        return

    if args.end_row is None:
        partial_dataset_msg = ""
    elif args.end_row == DEFAULT_FILE_ROWS_READ_LIMIT:
        partial_dataset_msg = f"(limited by default --end-row {args.end_row})"
    else:
        partial_dataset_msg = f"(limited by --end-row {args.end_row})"
    if args.end_row is not None and args.end_row not in df.shape:
        partial_dataset_msg = ""
    print("### Shape")
    print()
    print(df.shape, partial_dataset_msg)
    print()

    if args.columns_include:
        args.minimize_columns += [s.lstrip("-") for s in args.columns_include if s.startswith("-")]
        columns_include = [s.lstrip("-") for s in args.columns_include]

        # TODO: convert str categories like easy, hard, good, bad
        # if columns_include and the col is not numeric
        #     col.apply(words_to_numbers(args, words))
        alternatives = df[columns_include]
    else:
        alternatives = df.select_dtypes("number")
    alternatives = alternatives.drop(columns=args.columns_exclude)

    minimize_cols = set(args.minimize_columns)
    maximize_cols = set(alternatives.columns) - minimize_cols

    print("### Goals")
    print()
    if maximize_cols:
        print("#### Maximize")
        print_series(maximize_cols)
    if minimize_cols:
        print("#### Minimize")
        print_series(minimize_cols)

    # TODO: add --pairwise flag
    """
    from pymcdm.methods import COMET
    from pymcdm.methods.comet_tools import TriadSupportExpert

    # TODO: create useful subset?
    cvalues = [
            [0, 500, 1000],
            [1, 5]
            ]

    expert_function = TriadSupportExpert(
            criteria_names=['Price [$]', 'Profit [grade]'],
            filename='mej.csv',
            )

    comet = COMET(cvalues, expert_function)
    """

    data = auto_mcda(args, df, alternatives, minimize_cols)
    print_df(data)


def file_mcda(args, path):
    dfs = file_utils.read_file_to_dataframes(
        path,
        table_name=args.table_name,
        table_index=args.table_index,
        start_row=args.start_row,
        end_row=args.end_row,
        order_by=args.sort,
        encoding=args.encoding,
        mimetype=args.mimetype,
    )

    for df in dfs:
        print(f"## {path}:{df.name}")
        print_info(args, df)


def mcda():
    args = parse_args()
    for path in args.paths:
        file_mcda(args, path)


if __name__ == "__main__":
    mcda()
