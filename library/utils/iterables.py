import math, statistics
from collections import Counter
from collections.abc import Iterable, Iterator
from functools import wraps
from typing import Any

from library.utils import objects


def flatten(xs: Iterable) -> Iterator:
    for x in xs:
        if isinstance(x, dict):
            yield x
        elif isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        elif isinstance(x, bytes):
            yield x.decode("utf-8")
        else:
            yield x


def conform(list_: str | Iterable) -> list:
    if not list_:
        return []
    if not isinstance(list_, list):
        list_ = [list_]
    list_ = flatten(list_)
    list_ = list(filter(bool, list_))
    return list_


def safe_unpack(*list_, idx=0, keep_0=True) -> Any | None:
    list_ = conform(list_)
    if not list_:
        return None

    try:
        value = list_[idx]
        return value if keep_0 or value != 0 else None
    except IndexError:
        return None


def safe_pop(list_, idx=-1) -> Any | None:
    if not list_:
        return None
    return list_[idx]


def safe_len(list_) -> Any | None:
    if not list_:
        return 0
    try:
        return len(list_)
    except Exception:
        return len(str(list_))


def safe_index(list_, value) -> int:
    if not list_:
        return 0
    try:
        return list_.index(value)
    except ValueError:
        return -1


def get_all_lists(nested_dict):
    list_ = []

    for value in nested_dict.values():
        if isinstance(value, list):
            list_.append(value)
        elif isinstance(value, dict):
            list_.extend(get_all_lists(value))

    return list_


def get_list_with_most_items(nested_dict):
    list_ = get_all_lists(nested_dict)
    list_ = sorted(list_, key=len)
    return safe_pop(list_)


def safe_sum(*list_, keep_0=False) -> Any | None:
    list_ = conform(list_)
    if not list_:
        return None
    value = sum(list_)
    return value if keep_0 or value != 0 else None


def concat(*args):
    return (part for part in args if part)


def find_dict_value(input_list: list[dict], **kwargs) -> dict:
    for item in input_list:
        if all(item.get(k) == v for k, v in kwargs.items()):
            return item
    return {}


def find_none_keys(list_of_dicts, keep_0=True):
    none_keys = []

    if not list_of_dicts:
        return none_keys

    keys = list_of_dicts[0].keys()
    for key in keys:
        is_key_none = True
        for d in list_of_dicts:
            value = d.get(key)
            if value or (keep_0 and value == 0):
                is_key_none = False
                break
        if is_key_none:
            none_keys.append(key)

    return none_keys


def list_dict_filter_bool(media: list[dict], keep_0=True) -> list[dict]:
    keys_to_remove = find_none_keys(media, keep_0=keep_0)
    return [d for d in [{k: v for k, v in m.items() if k not in keys_to_remove} for m in media] if d]


def list_dict_filter_keys(media: list[dict], keys) -> list[dict]:
    return [d for d in [objects.dict_filter_keys(d, keys) for d in media] if d]


def list_dict_filter_unique(data: list[dict]) -> list[dict]:
    if len(data) == 0:
        return []

    unique_values = {}
    for key in set.intersection(*(set(d.keys()) for d in data)):
        values = {d[key] for d in data if key in d}
        if len(values) > 1:
            unique_values[key] = values
    filtered_data = [{k: v for k, v in d.items() if k in unique_values} for d in data]
    return filtered_data


def list_dict_unique(data: list[dict], unique_keys: list[str]) -> list[dict]:
    seen = set()
    list_ = []
    for d in data:
        t = tuple(d[key] for key in unique_keys)

        if t not in seen:
            seen.add(t)
            list_.append(d)

    return list_


def list_dict_value_counts(list_of_dicts, key_name):
    category_counts = {}
    for item in list_of_dicts:
        category = item.get(key_name)
        if category is not None:
            category_counts[category] = category_counts.get(category, 0) + 1

    for item in list_of_dicts:
        category = item.get(key_name)
        if category is not None and category in category_counts:
            item[f"{key_name}_count"] = category_counts[category]

    return list_of_dicts


def chunks(lst, n) -> Iterator:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def divisors_upto_sqrt(n: int) -> Iterator:
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0:
            yield i
            if i * i != n:
                yield int(n / i)


def ordered_set(items):
    seen = set()
    for item in items:
        if item not in seen:
            yield item
            seen.add(item)


def return_unique(gen_func, ext_fn=None):
    seen = set()

    @wraps(gen_func)
    def wrapper(*args, **kwargs):
        for item in gen_func(*args, **kwargs):
            t = item if ext_fn is None else ext_fn(item)
            if t in seen:
                continue
            seen.add(t)
            yield item

    return wrapper


def return_unique_set_items(gen_func):
    seen = set()

    def wrapper(*args, **kwargs):
        for item in gen_func(*args, **kwargs):
            diff = item - seen
            if diff:
                seen.update(item)
                yield diff

    return wrapper


def multi_split(string, delimiters):
    delimiters = tuple(delimiters)
    stack = [
        string,
    ]

    for delimiter in delimiters:
        for i, substring in enumerate(stack):
            substack = substring.split(delimiter)
            stack.pop(i)
            for j, _substring in enumerate(substack):
                stack.insert(i + j, _substring)

    return stack


def divide_sequence(arr):
    result = arr[0]
    if result == 0:
        return float("inf")
    elif 0 in arr:
        return float("-inf")
    for i in range(1, len(arr)):
        result = result / arr[i]
    return result


def zipkw(**kwargs):
    keys = list(kwargs.keys())
    values = list(kwargs.values())

    # Ensure all lists are of the same length
    lengths = [len(v) for v in values]
    if len(set(lengths)) != 1:
        raise ValueError("All keyword argument lists must be of the same length")

    for combination in zip(*values):
        yield dict(zip(keys, combination))


def value_counts(input_list):
    counts = Counter(input_list)
    return [counts[item] for item in input_list]


def similarity(list1, list2) -> float:
    if list1 is None or not list1 or list2 is None or not list2:
        return 0.0

    set1 = set(list1)
    set2 = set(list2)

    common_elements = len(set1.intersection(set2))
    total_unique_elements = len(set1.union(set2))

    if total_unique_elements == 0:
        return 0.0

    return common_elements / total_unique_elements


def list_dict_summary(l, stat_funcs={"Total": sum, "Median": statistics.median}):
    summary = {}
    for d in l:
        for key, value in d.items():
            if isinstance(value, (int, float)):
                if key not in summary:
                    summary[key] = []
                summary[key].append(value)

    summary_dicts = []
    for stat_name, stat_func in stat_funcs.items():
        stat_result = {}
        for key, values in summary.items():
            if key in ("count",):
                stat_result[key] = int(stat_func(values))
            else:
                stat_result[key] = stat_func(values)

        summary_dicts.append({"path": stat_name, **stat_result})

    return summary_dicts
