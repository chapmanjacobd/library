from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, file_utils, iterables, objects, pd_utils, sql_utils, web
from library.utils.consts import DEFAULT_FILE_ROWS_READ_LIMIT
from library.utils.printing import print_df, print_series

COMET_MAX_CRITERIA = 12
MATRIX_DIMENSIONS = 2
NO_CRITERIA = 0
PCA_MIN_ROWS = 2


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
    parser.add_argument(
        "--weights",
        "--weight",
        nargs="*",
        action=argparse_utils.ArgparseList,
        default=None,
        metavar="WEIGHT",
        help="Criterion weights as values or COLUMN=VALUE pairs; values are normalized.",
    )
    parser.add_argument(
        "--categorical",
        "--convert-categorical",
        action="store_true",
        help="Convert non-numeric included columns using the word-to-number map.",
    )
    parser.add_argument(
        "--categorical-columns",
        "--categorical-cols",
        nargs="*",
        action=argparse_utils.ArgparseList,
        default=[],
        metavar="COLUMN",
        help="Columns to convert from categorical words to numeric values.",
    )
    parser.add_argument(
        "--pca",
        action="store_true",
        help="Print PCA feature-contribution diagnostics before ranking.",
    )
    parser.add_argument(
        "--pca-threshold",
        type=float,
        default=0.03,
        help="Warn when a PCA feature contribution is below this fraction (default: 0.03).",
    )
    parser.add_argument(
        "--pairwise",
        "--pairwise-ranking",
        action="store_true",
        help="Add a weighted pairwise preference ranking.",
    )
    parser.add_argument(
        "--comet",
        "--comet-ranking",
        action="store_true",
        help="Add a deterministic COMET ranking using TOPSIS as the expert.",
    )
    parser.add_argument(
        "--mcda-method",
        type=lambda value: value.upper(),
        choices=["TOPSIS", "MABAC", "BORDA", "PAIRWISE", "COMET"],
        help="Method used to sort output (default: TOPSIS).",
    )
    parser.add_argument("--nodata", type=int, default=0)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--sort", "-u", default="random()")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    if args.words_nums_map:
        mappings_path = Path(args.words_nums_map)
        if not mappings_path.exists() or mappings_path.stat().st_size == 0:
            mappings_path.write_text("{}")

    arggroups.table_like_post(args)

    if not 0 <= args.pca_threshold <= 1:
        parser.error("--pca-threshold must be between 0 and 1")
    if args.mcda_method == "PAIRWISE":
        args.pairwise = True
    elif args.mcda_method == "COMET":
        args.comet = True

    return args


def words_to_numbers(args, words):
    from contextlib import nullcontext

    default = {
        "high": 5,
        "above average": 4,
        "average": 3,
        "below average": 2,
        "low": 1,
    }

    numbers = []
    mappings_file = getattr(args, "words_nums_map", None)
    mappings_context = objects.json_shelve(mappings_file, default) if mappings_file else nullcontext(default)
    with mappings_context as mappings:
        for word in words:
            if word is None:
                numbers.append(getattr(args, "nodata", 0))
                continue

            try:
                import pandas as pd

                if pd.isna(word):
                    numbers.append(getattr(args, "nodata", 0))
                    continue
            except (TypeError, ValueError):
                pass

            if isinstance(word, (int, float)):
                numbers.append(word)
                continue

            word = str(word).strip().lower()

            try:
                number = mappings[word]
            except KeyError:  # word not in mappings
                try:
                    number = int(input(f"Enter a number for '{word}': "))
                except (EOFError, OSError) as e:
                    message = (
                        f"No numeric mapping for category {word!r}; add it to --words-nums-map "
                        "or run interactively to provide one."
                    )
                    raise ValueError(message) from e
                mappings[word] = number  # save it for the future

            try:
                numbers.append(float(number))
            except (TypeError, ValueError) as e:
                message = f"Category mapping for {word!r} must be numeric, got {number!r}"
                raise ValueError(message) from e

    return numbers


def _normalise_method(args):
    method = getattr(args, "mcda_method", None)
    return method.upper() if isinstance(method, str) else method


def _parse_weight_value(value, column):
    try:
        import math

        value = float(value)
    except (TypeError, ValueError) as e:
        message = f"Weight for {column!r} must be numeric, got {value!r}"
        raise ValueError(message) from e
    if not math.isfinite(value) or value < 0:
        message = f"Weight for {column!r} must be finite and non-negative"
        raise ValueError(message)
    return value


def _requested_weight_pairs(requested, columns):
    if isinstance(requested, dict):
        return list(requested.items())
    if isinstance(requested, str):
        requested = [requested]
    tokens = [str(token).strip() for token in requested if str(token).strip()]
    if not tokens:
        raise ValueError("--weights requires at least one value")
    named = ["=" in token or ":" in token for token in tokens]
    if any(named) and not all(named):
        raise ValueError("--weights must use either positional values or COLUMN=VALUE pairs, not both")
    if all(named):
        pairs = []
        seen_columns = set()
        for token in tokens:
            separator = "=" if "=" in token else ":"
            column, value = (part.strip() for part in token.split(separator, 1))
            if not column:
                message = f"Invalid weight specification {token!r}"
                raise ValueError(message)
            if column in seen_columns:
                message = f"Weight specified more than once for column {column!r}"
                raise ValueError(message)
            seen_columns.add(column)
            pairs.append((column, value))
        return pairs
    if len(tokens) != len(columns):
        message = f"--weights requires {len(columns)} values, got {len(tokens)}"
        raise ValueError(message)
    return list(zip(columns, tokens, strict=True))


def criterion_weights(args, columns, matrix):
    """Return normalized criterion weights, using entropy weights by default."""
    import numpy as np
    from pymcdm import weights as pymcdm_weights

    columns = list(columns)
    requested = getattr(args, "weights", None)
    if requested is None or requested == []:
        return pymcdm_weights.entropy_weights(matrix)
    pairs = _requested_weight_pairs(requested, columns)
    values = {column: _parse_weight_value(value, column) for column, value in pairs}
    unknown = set(values) - set(columns)
    if unknown:
        message = f"Unknown weight column(s): {', '.join(sorted(unknown))}"
        raise ValueError(message)
    missing = set(columns) - set(values)
    if missing:
        message = f"Missing weight column(s): {', '.join(sorted(missing))}"
        raise ValueError(message)
    weights = np.array([values[column] for column in columns], dtype=float)
    total = weights.sum()
    if total <= 0:
        raise ValueError("At least one criterion weight must be greater than zero")
    return weights / total


def convert_categorical_columns(df, args, columns):
    """Convert selected categorical columns to numeric ordinal values."""
    import pandas as pd

    converted = df.copy()
    for column in columns:
        if column not in converted.columns:
            message = f"Categorical column not found: {column}"
            raise ValueError(message)
        if not pd.api.types.is_numeric_dtype(converted[column]):
            converted[column] = words_to_numbers(args, converted[column].tolist())
    return converted


def _oriented_scores(matrix, goal_directions):
    import numpy as np

    matrix = np.asarray(matrix, dtype=float)
    scores = np.empty_like(matrix, dtype=float)
    for index, direction in enumerate(goal_directions):
        values = matrix[:, index]
        low, high = values.min(), values.max()
        if high == low:
            scores[:, index] = 0.5
        elif direction == 1:
            scores[:, index] = (values - low) / (high - low)
        else:
            scores[:, index] = (high - values) / (high - low)
    return scores


def pairwise_rank(matrix, weights, goal_directions):
    """Rank alternatives by their weighted average pairwise preference."""
    import numpy as np

    scores = _oriented_scores(matrix, goal_directions)
    comparisons = (
        (scores[:, None, :] > scores[None, :, :]).astype(float)
        + 0.5 * (scores[:, None, :] == scores[None, :, :])
    )
    pairwise_preferences = np.sum(comparisons * np.asarray(weights), axis=2)
    return pairwise_preferences.mean(axis=1)


def comet_rank(matrix, weights, goal_directions):
    """Calculate a deterministic COMET ranking without interactive expert prompts."""
    import numpy as np
    from pymcdm.methods import COMET, TOPSIS
    from pymcdm.methods.comet_tools import MethodExpert

    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape[1] > COMET_MAX_CRITERIA:
        raise ValueError("COMET is limited to 12 criteria to avoid exponential characteristic-object growth")

    cvalues = []
    for index in range(matrix.shape[1]):
        low, high = matrix[:, index].min(), matrix[:, index].max()
        if low == high:
            delta = max(abs(low) * 1e-6, 1e-6)
            cvalues.append([low - delta, high + delta])
        else:
            cvalues.append([low, high])

    expert = MethodExpert(TOPSIS(), np.asarray(weights), np.asarray(goal_directions))
    return COMET(cvalues, expert)(matrix, validation=True)


def pca_diagnostics(alternatives):
    """Return PCA-based feature contributions as fractions of total variance."""
    import numpy as np
    import pandas as pd

    matrix = np.asarray(alternatives, dtype=float)
    matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    columns = list(alternatives.columns)
    if matrix.ndim != MATRIX_DIMENSIONS or matrix.shape[1] == NO_CRITERIA:
        return pd.DataFrame(columns=["criterion", "variance_fraction", "variance_percent"])
    if matrix.shape[0] < PCA_MIN_ROWS:
        contributions = np.zeros(matrix.shape[1], dtype=float)
    else:
        centered = matrix - matrix.mean(axis=0)
        scale = centered.std(axis=0)
        scale[scale == 0] = 1
        standardized = centered / scale
        _, singular_values, components = np.linalg.svd(standardized, full_matrices=False)
        explained = singular_values**2
        explained /= explained.sum() or 1
        contributions = (components**2).T @ explained
        contributions /= contributions.sum() or 1
    return pd.DataFrame(
        {
            "criterion": columns,
            "variance_fraction": contributions,
            "variance_percent": contributions * 100,
        }
    ).sort_values("variance_fraction", ascending=False, ignore_index=True)


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

    selected_method = _normalise_method(args)
    pairwise_enabled = getattr(args, "pairwise", False) or selected_method == "PAIRWISE"
    comet_enabled = getattr(args, "comet", False) or selected_method == "COMET"

    if len(alternatives) > 1:
        from pymcdm.methods import MABAC, TOPSIS

        goal_directions = np.array([-1 if col in minimize_cols else 1 for col in alternatives.columns])
        raw_alternatives_np = alternatives.fillna(getattr(args, "nodata", None) or 0).to_numpy()
        alternatives_np = raw_alternatives_np.copy()

        # Ensure strictly positive for pymcdm 1.4.0+ entropy_weights/sum_normalization
        if np.any(alternatives_np <= 0):
            alternatives_np = np.where(alternatives_np <= 0, 1e-9, alternatives_np)

        weights = criterion_weights(args, alternatives.columns, alternatives_np)

        methods = [TOPSIS(), MABAC()]
        method_names = ["TOPSIS", "MABAC"]
        votes = []
        for ranking_method in methods:
            pref = ranking_method(alternatives_np, weights, goal_directions)
            votes.append(pref)
        if pairwise_enabled:
            votes.append(pairwise_rank(raw_alternatives_np, weights, goal_directions))
            method_names.append("PAIRWISE")
        if comet_enabled:
            votes.append(comet_rank(raw_alternatives_np, weights, goal_directions))
            method_names.append("COMET")
        votes_df = pd.DataFrame(dict(zip(method_names, votes, strict=True)), index=alternatives.index)
        borda_points = borda(votes_df, weights=[1] * len(votes))
        borda_df = pd.DataFrame({"BORDA": borda_points}, index=votes_df.index)
        votes_df = pd.concat((votes_df, borda_df), axis=1)
    else:
        scores = {"TOPSIS": [0.5], "MABAC": [0.5]}
        if pairwise_enabled:
            scores["PAIRWISE"] = [0.5]
        if comet_enabled:
            scores["COMET"] = [0.5]
        scores["BORDA"] = [0.5]
        votes_df = pd.DataFrame(scores, index=alternatives.index)

    dfs = []
    if df is not None:
        dfs.append(df)
    dfs.extend((votes_df,))
    df = pd.concat(dfs, axis=1)
    df["original_index"] = df.index
    selected_method = selected_method or "TOPSIS"
    if selected_method not in df.columns:
        message = f"MCDA method {selected_method!r} is not available; enable its CLI option first"
        raise ValueError(message)
    df = df.sort_values(selected_method, ascending=False)
    df = df.reset_index(drop=True)
    df["sorted_index"] = df.index
    return df


def _select_alternatives(args, df):
    import pandas as pd

    columns_include = list(getattr(args, "columns_include", []) or [])
    categorical_columns = list(getattr(args, "categorical_columns", []) or [])
    if categorical_columns:
        missing = set(categorical_columns) - set(df.columns)
        if missing:
            message = f"Categorical column(s) not found: {', '.join(sorted(missing))}"
            raise ValueError(message)
        columns_include.extend(column for column in categorical_columns if column not in columns_include)

    if columns_include:
        args.minimize_columns += [s.lstrip("-") for s in columns_include if s.startswith("-")]
        columns_include = [s.lstrip("-") for s in columns_include]
        should_convert = getattr(args, "categorical", False) or bool(categorical_columns) or bool(
            getattr(args, "words_nums_map", None)
        )
        if should_convert:
            conversion_columns = categorical_columns or [
                column for column in columns_include if not pd.api.types.is_numeric_dtype(df[column])
            ]
            df = convert_categorical_columns(df, args, conversion_columns)
        alternatives = df[columns_include]
    else:
        alternatives = df.select_dtypes("number")
        if categorical_columns:
            df = convert_categorical_columns(df, args, categorical_columns)
            alternatives = pd.concat((alternatives, df[categorical_columns]), axis=1)
    return df, alternatives.drop(columns=getattr(args, "columns_exclude", []), errors="ignore")


def _print_pca_diagnostics(args, alternatives):
    import warnings

    diagnostics = pca_diagnostics(alternatives)
    threshold = getattr(args, "pca_threshold", 0.03)
    low_variance = diagnostics.loc[diagnostics["variance_fraction"] < threshold, "criterion"].tolist()
    if low_variance:
        message = f"PCA criteria below {threshold:.1%} variance contribution: {', '.join(low_variance)}"
        warnings.warn(message, UserWarning, stacklevel=2)
    print("### PCA diagnostics")
    print_df(diagnostics)


def print_info(args, dft):
    import pandas as pd

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
    if args.end_row is not None and args.end_row != df.shape[0]:
        partial_dataset_msg = ""
    print("### Shape")
    print()
    print(df.shape, partial_dataset_msg)
    print()

    df, alternatives = _select_alternatives(args, df)

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

    if not all(pd.api.types.is_numeric_dtype(alternatives[column]) for column in alternatives.columns):
        non_numeric = [column for column in alternatives if not pd.api.types.is_numeric_dtype(alternatives[column])]
        message = (
            f"Non-numeric MCDA criteria: {', '.join(non_numeric)}. "
            "Use --categorical-columns or --categorical to convert them."
        )
        raise ValueError(message)

    if getattr(args, "pca", False):
        _print_pca_diagnostics(args, alternatives)

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
        print_info(args, (df_name, df))


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
                return (0, -x["size"] / x["exists"]) if x["exists"] else (1, -x["size"] / (x["total"] or 1))

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
