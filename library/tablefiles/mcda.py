from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, file_utils, iterables, objects, pd_utils, sql_utils, web
from library.utils.consts import DEFAULT_FILE_ROWS_READ_LIMIT
from library.utils.printing import print_df, print_series


def parse_args():
    parser = argparse_utils.ArgumentParser(description="Perform MCDA on one or more files", usage=usage.mcda)
    arggroups.table_like(parser)
    parser.add_argument(
        "--minimize-columns",
        "--minimize-cols",
        "--minimize",
        "--min",
        nargs="*",
        action=argparse_utils.ArgparseList,
        default=[],
    )
    parser.add_argument(
        "--columns-exclude",
        "--exclude-columns",
        "--ignore-columns",
        nargs="*",
        action=argparse_utils.ArgparseList,
        default=[],
    )
    parser.add_argument(
        "--columns-include",
        "--include-columns",
        nargs="*",
        action=argparse_utils.ArgparseList,
        default=[],
    )
    parser.add_argument("--words-nums-map")
    parser.add_argument("--mcda-method")
    parser.add_argument("--nodata", type=int, default=0)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--sort", "-u", default="random()")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    if args.words_nums_map:
        Path(args.words_nums_map).touch()

    arggroups.table_like_post(args)

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


def auto_mcda(args, alternatives, minimize_cols, df=None):
    import numpy as np
    import pandas as pd

    if len(alternatives) > 1:
        from pymcdm import weights as w
        from pymcdm.methods import MABAC, TOPSIS

        goal_directions = np.array([-1 if col in minimize_cols else 1 for col in alternatives.columns])
        alternatives_np = alternatives.fillna(getattr(args, "nodata", None) or 0).to_numpy()
        weights = w.entropy_weights(alternatives_np)

        methods = [TOPSIS(), MABAC()]
        method_names = ["TOPSIS", "MABAC"]
        votes = []
        for method in methods:
            # TODO: --weights flag to override
            pref = method(alternatives_np, weights, goal_directions)
            votes.append(pref)
        votes_df = pd.DataFrame(zip(*votes, strict=False), columns=method_names)
        borda_points = borda(votes_df, weights=[1] * len(votes))
        borda_df = pd.DataFrame({"BORDA": borda_points}, index=votes_df.index)
        votes_df = pd.concat((votes_df, borda_df), axis=1)

        # TODO: PCA option and warning if a criterion accounts for less than 3% of variance
    else:
        votes_df = pd.DataFrame({"TOPSIS": [0.5], "MABAC": [0.5], "BORDA": [0.5]})

    dfs = []
    if df is not None:
        dfs.append(df)
    dfs.extend((votes_df,))
    df = pd.concat(dfs, axis=1)
    df["original_index"] = df.index
    df = df.sort_values(getattr(args, "mcda_method", None) or "TOPSIS", ascending=False)
    df = df.reset_index(drop=True)
    df["sorted_index"] = df.index
    return df


def print_info(args, dft):
    df_name, df = dft

    if df.shape == (0, 0):
        print(f"Table [{df_name}] empty")
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

    if alternatives.empty:
        print("No alternatives could be identified. The data likely needs to be cleaned...")
        print("You can try running with --clean but compare the output with the original data:")
        print_df(df.head(5))
        return

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

    data = auto_mcda(args, alternatives, minimize_cols, df=df)
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
        join_tables=args.join_tables,
        transpose=args.transpose,
        skip_headers=args.skip_headers,
    )

    for dft in dfs:
        df_name, df = dft
        if args.table_name == "stdin":
            print(f"## stdin:{df_name}")
        else:
            print(f"## {path}:{df_name}")
        df = pd_utils.convert_dtypes(df, clean=args.clean)
        print_info(args, dft)


def mcda():
    args = parse_args()
    web.requests_session(args)  # configure session
    for path in args.paths:
        file_mcda(args, path)


def mcda_sorted(args, keys: list[tuple]):
    import pandas as pd

    def get_ranks(series):
        return series.rank(method="dense").astype(int)

    # log.debug("mcda_sorted key: %s", keys)
    alternatives = pd.DataFrame(keys).apply(get_ranks)

    df = auto_mcda(args, alternatives, minimize_cols=alternatives.columns)
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

    df = auto_mcda(args, alternatives, minimize_cols={s.lstrip("-") for s in columns if s.startswith("-")}, df=df)
    df = df.drop(columns=["original_index", "sorted_index"])
    return df


def group_sort_by(args, folders):
    if args.sort_groups_by is None:

        def sort_func(x):
            if not getattr(args, "hide_deleted", True):
                return (0, -x["deleted_size"] / x["deleted"]) if x["deleted"] else (1, -x["deleted_size"] / x["total"])
            else:
                return (0, -x["size"] / x["exists"]) if x["exists"] else (1, -x["size"] / x["total"])

    elif args.sort_groups_by.startswith("mcda "):
        import pandas as pd

        if not isinstance(folders, pd.DataFrame):
            folders = pd.DataFrame(folders)
        values = args.sort_groups_by.replace("mcda ", "", 1)
        df = sort(args, folders, values)
        return df.drop(columns=["TOPSIS", "MABAC", "BORDA"]).to_dict(orient="records")
    elif args.sort_groups_by == "played_ratio":

        def sort_func(x):
            return (0, x["played"] / x["deleted"]) if x["deleted"] else (1, x["played"] / x["total"])

    elif args.sort_groups_by == "deleted_ratio":

        def sort_func(x):
            return (0, x["deleted"] / x["played"]) if x["played"] else (1, x["deleted"] / x["total"])

    else:
        sort_func = sql_utils.sort_like_sql(args.sort_groups_by)  # type: ignore

    return sorted(folders, key=sort_func)
